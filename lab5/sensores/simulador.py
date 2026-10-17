"""
Simulador de una boda  ->  API Gateway (POST /eventos)  ->  Kinesis

Genera los eventos que le importan a un wedding planner y los manda por HTTP a
API Gateway, igual que lo haría la web de RSVP, WhatsApp o el escáner de la puerta:

  invitacion  se envió la invitación                      (fase 1)
  rsvp        el invitado confirma o cancela, con menú     (fase 2, web / WhatsApp / llamada)
  asiento     el planner asigna mesa y silla               (fase 3)
  rsvp        algunas cancelaciones de último momento      (fase 3)
  checkin     el invitado llega a la puerta (QR / pulsera)  (fase 4, el día de la boda)

Las semanas de preparación se aceleran: cada fase dura --segundos-por-fase
(60 s por defecto, ~4 min la demo completa).

Errores a propósito para la demo:
  - una mesa queda con sobrecupo (11-12 personas)
  - 1-2 "colados": llega alguien que no confirmó o que canceló
  - --corruptos 0.05 manda 5% de registros rotos (terminan en la DLQ)

Ejemplos:
  py simulador.py
  py simulador.py --invitados 150 --segundos-por-fase 45
  py simulador.py --corruptos 0.05

LÍMITES DE SEGURIDAD (presupuesto del Learner Lab):
  máximo 200 invitados, 20 registros/s y 15 minutos por corrida.
"""
import argparse
import json
import random
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import api

MAX_INVITADOS = 200
MAX_REGISTROS_POR_SEG = 20
MAX_MINUTOS = 15
SILLAS_POR_MESA = 10

NOMBRES = ["Ana", "Luis", "María", "José", "Sofía", "Diego", "Valeria", "Carlos", "Fernanda",
           "Jorge", "Daniela", "Miguel", "Paola", "Ricardo", "Camila", "Andrés", "Lucía",
           "Alejandro", "Regina", "Emilio", "Ximena", "Rodrigo", "Mariana", "Javier", "Renata",
           "Santiago", "Elena", "Pablo", "Gabriela", "Héctor", "Isabel", "Tomás"]
APELLIDOS = ["García", "Hernández", "López", "Martínez", "González", "Pérez", "Rodríguez",
             "Sánchez", "Ramírez", "Flores", "Torres", "Rivera", "Gómez", "Díaz", "Cruz",
             "Morales", "Reyes", "Gutiérrez", "Ortiz", "Castillo", "Navarro", "Vargas"]
MENUS = (["res", "pollo", "vegetariano", "infantil"], [45, 35, 12, 8])
RESTRICCIONES = ["sin gluten", "alergia a nueces", "vegano", "sin lácteos", "alergia a mariscos"]
CANALES = (["web", "whatsapp", "llamada"], [55, 35, 10])


def ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Invitado:
    def __init__(self, n: int):
        self.id = f"inv-{n:03d}"
        self.nombre = f"{random.choice(NOMBRES)} {random.choice(APELLIDOS)}"
        self.lado = random.choice(["novia", "novio"])
        self.estado = "pendiente"


def evento(boda_id: str, inv: Invitado, tipo: str, **datos) -> dict:
    return {"evento_id": uuid.uuid4().hex, "boda_id": boda_id, "invitado_id": inv.id,
            "nombre": inv.nombre, "tipo": tipo, "ts": ahora_iso(), **datos}


# --------------------------------------------------------------- fases
def fase_invitaciones(boda_id, invitados):
    return [lambda i=i: evento(boda_id, i, "invitacion", lado=i.lado) for i in invitados]


def fase_rsvp(boda_id, invitados):
    planes = []
    for inv in invitados:
        if random.random() < 0.08:  # nunca contesta -> se queda "pendiente"
            continue

        def rsvp(inv=inv):
            if random.random() < 0.84:
                inv.estado = "confirmado"
                extra = {"menu": random.choices(*MENUS)[0]}
                if random.random() < 0.1:
                    extra["restriccion"] = random.choice(RESTRICCIONES)
            else:
                inv.estado = "cancelado"
                extra = {}
            return evento(boda_id, inv, "rsvp", respuesta=inv.estado,
                          canal=random.choices(*CANALES)[0], **extra)
        planes.append(rsvp)
    return planes


def fase_mesas(boda_id, invitados):
    """El planner acomoda a los confirmados. Una mesa queda con sobrecupo a propósito
    y algunos cancelan de último momento."""
    planes = []
    confirmados = [i for i in invitados if i.estado == "confirmado"]
    random.shuffle(confirmados)
    mesa_sobrecupo = random.randint(2, max(2, len(confirmados) // SILLAS_POR_MESA))
    mesa, silla = 1, 1
    for inv in confirmados:
        limite = SILLAS_POR_MESA + 2 if mesa == mesa_sobrecupo else SILLAS_POR_MESA
        if silla > limite:
            mesa, silla = mesa + 1, 1
        planes.append(lambda i=inv, m=mesa, s=silla: evento(boda_id, i, "asiento", mesa=m, asiento=s))
        silla += 1

    for inv in random.sample(confirmados, k=min(3, len(confirmados))):
        def cancelar(inv=inv):
            inv.estado = "cancelado"
            return evento(boda_id, inv, "rsvp", respuesta="cancelado", canal="whatsapp",
                          ultimo_momento=True)
        planes.append(cancelar)
    return planes


def fase_llegadas(boda_id, invitados):
    """Día de la boda: ~90% de los confirmados llegan y hay 1-2 colados."""
    llegan = [i for i in invitados if i.estado == "confirmado" and random.random() < 0.9]
    no_confirmados = [i for i in invitados if i.estado != "confirmado"]
    llegan += random.sample(no_confirmados, k=min(2, len(no_confirmados)))
    random.shuffle(llegan)
    metodo = (["qr", "pulsera_nfc", "lista"], [70, 25, 5])
    return [lambda i=i: evento(boda_id, i, "checkin", metodo=random.choices(*metodo)[0],
                               puerta="principal") for i in llegan]


FASES = [
    ("1. Invitaciones enviadas", fase_invitaciones),
    ("2. Confirmaciones (RSVP)", fase_rsvp),
    ("3. Acomodo de mesas y cancelaciones", fase_mesas),
    ("4. Día de la boda: llegadas", fase_llegadas),
]


# --------------------------------------------------------------- envío
def enviar(api_url, eventos, prob_corrupto):
    """POST /eventos en lotes de hasta 25 eventos. Devuelve (aceptados, fallidos)."""
    if not eventos:
        return 0, 0
    cuerpo = []
    for e in eventos:
        if random.random() < prob_corrupto:
            cuerpo.append(json.dumps(e, ensure_ascii=False)[:60])  # JSON roto -> DLQ
        else:
            cuerpo.append(e)
    ok = fail = 0
    for i in range(0, len(cuerpo), 25):
        lote = cuerpo[i : i + 25]
        status, resp, _ = api.post(f"{api_url}/eventos", lote)
        if status == 202:
            ok += resp.get("aceptados", 0)
            fail += resp.get("fallidos_kinesis", 0) + resp.get("rechazados", 0)
        else:
            fail += len(lote)
            print(f"  ⚠️ API respondió {status}: {str(resp)[:120]}")
    return ok, fail


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--invitados", type=int, default=100)
    p.add_argument("--segundos-por-fase", type=int, default=60)
    p.add_argument("--boda-id", default=None, help="por defecto boda-ana-y-luis-HHMM (una boda nueva por corrida)")
    p.add_argument("--corruptos", type=float, default=0.0, help="fracción de registros rotos")
    args = p.parse_args()

    # ---------- límites de seguridad ----------
    if not 10 <= args.invitados <= MAX_INVITADOS:
        sys.exit(f"--invitados debe estar entre 10 y {MAX_INVITADOS}")
    if args.segundos_por_fase < 10:
        sys.exit("--segundos-por-fase mínimo 10")
    if args.invitados / args.segundos_por_fase > MAX_REGISTROS_POR_SEG:
        sys.exit(f"Demasiado rápido: más de {MAX_REGISTROS_POR_SEG} registros/s. "
                 "Sube --segundos-por-fase o baja --invitados.")
    if args.segundos_por_fase * len(FASES) > MAX_MINUTOS * 60:
        sys.exit(f"La corrida duraría más de {MAX_MINUTOS} min.")

    api_url = api.url_base()
    if args.boda_id is None:
        args.boda_id = "boda-ana-y-luis-" + datetime.now().strftime("%H%M")

    invitados = [Invitado(n + 1) for n in range(args.invitados)]
    print(f"💍 {args.boda_id}: {args.invitados} invitados -> {api_url}/eventos")
    print(f"   {len(FASES)} fases de {args.segundos_por_fase} s\n")

    total_ok = total_fail = 0
    try:
        for nombre_fase, generar in FASES:
            planes = generar(args.boda_id, invitados)
            print(f"── {nombre_fase} ({len(planes)} eventos) ──")
            # Reparte los eventos de la fase en momentos aleatorios dentro de la fase
            # (en la fase 3 se respeta el orden: primero mesas, al final las cancelaciones)
            momentos = sorted(random.uniform(0, args.segundos_por_fase * 0.9) for _ in planes)
            if generar is not fase_mesas:
                random.shuffle(planes)
            inicio = time.time()
            pendientes = list(zip(momentos, planes))
            while pendientes or time.time() - inicio < args.segundos_por_fase:
                transcurrido = time.time() - inicio
                listos = [plan for m, plan in pendientes if m <= transcurrido]
                pendientes = [(m, plan) for m, plan in pendientes if m > transcurrido]
                eventos = [plan() for plan in listos]
                ok, fail = enviar(api_url, eventos, args.corruptos)
                total_ok += ok
                total_fail += fail
                for e in eventos[:3]:
                    extra = e.get("respuesta") or (f"mesa {e['mesa']}" if "mesa" in e else e.get("metodo", ""))
                    if e.get("ultimo_momento"):
                        extra += " ⚠️ último momento"
                    print(f"  {e['tipo']:<10} {e['nombre']:<24} {extra}")
                if len(eventos) > 3:
                    print(f"  ... y {len(eventos) - 3} más")
                if not pendientes and time.time() - inicio >= args.segundos_por_fase:
                    break
                time.sleep(1)

            conf = sum(i.estado == "confirmado" for i in invitados)
            canc = sum(i.estado == "cancelado" for i in invitados)
            print(f"   → confirmados {conf} | cancelados {canc} | "
                  f"pendientes {args.invitados - conf - canc}\n")
    except KeyboardInterrupt:
        print("\nDetenido.")

    print(f"Aceptados por API Gateway -> Kinesis: {total_ok:,} | fallidos: {total_fail}")
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
