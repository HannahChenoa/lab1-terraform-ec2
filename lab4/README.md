# Lab 4 - Lambda + ALB + ElastiCache (Redis) + RDS (MySQL)

DSE - ITESO. Infraestructura 100% en Terraform, cuenta de **AWS Academy Learner Lab**.

## Arquitectura

```
Internet -> ALB (HTTP:80) -> Lambda (Node.js, target_type=lambda)
                                  |            |
                                  v            v
                         ElastiCache Redis   RDS MySQL
                         (cache-aside)       (fuente de verdad)
```

- La Lambda vive dentro de la VPC default para poder hablar por red privada
  con RDS y ElastiCache (ninguno de los dos es público).
- `GET /item/{id}` hace **cache-aside**: primero busca en Redis; si no está,
  consulta MySQL (con un `SLEEP(0.15)` a propósito para simular una consulta
  "cara") y guarda el resultado en Redis por `cache_ttl_seconds` (default 300s).
- `GET /health` es el health check que usa el Target Group del ALB.
- En AWS Academy no se pueden crear IAM roles nuevos, así que la Lambda
  reutiliza el `LabRole` que ya trae la cuenta (variable `lambda_role_name`).
- El state de Terraform se guarda en el mismo bucket S3 que ya usan lab1-3
  (`hannah.puente`, key `lab4/terraform.tfstate`).

## 0. Requisitos (en TU terminal, no en este chat)

Importante: no pude correr `terraform apply` ni compilar `wrk2` desde este
chat -> tanto mi contenedor en la nube como el shell que uso en tu compu
tienen bloqueado por política de red el acceso a los endpoints de AWS y al
registro de Terraform (lo probé y ambos regresan 403 del proxy). Tu terminal
normal (la que ya usaste para lab1-3) sí tiene internet completo, así que
todo lo de abajo lo corres tú ahí.

Necesitas:
- Terraform >= 1.5
- AWS CLI (o solo el archivo `~/.aws/credentials`)
- Node.js + npm (para empaquetar la Lambda) - ya lo tienes si hiciste otros labs
- `wrk2` compilado (ver sección de load testing más abajo)

## 1. Configura tus credenciales de AWS Academy

En el Learner Lab (curso 186884) -> "AWS Details" -> copia el bloque de
credenciales temporales y pégalo en `~/.aws/credentials` bajo el profile
`academy` (el mismo que ya usan lab1, lab2 y lab3):

```ini
[academy]
aws_access_key_id = ASIA...
aws_secret_access_key = ...
aws_session_token = ...
```

**Importante de seguridad:** estas credenciales son temporales (empiezan con
`ASIA`) y expiran en unas horas, pero mientras son válidas dan acceso real a
tu cuenta. No las pegues en chats, tickets, ni las subas al repo. El
`.gitignore` de este lab ya excluye `.pem`, `.tfstate` y `.terraform/`, pero
las credenciales viven fuera del repo, en tu `~/.aws/credentials` - ahí deben
quedarse.

## 2. Deploy con Terraform

```bash
cd lab4
terraform init
terraform plan
terraform apply
```

`terraform apply` va a: correr `npm install` dentro de `lambda/` (te
descarga `mysql2` e `ioredis`), empaquetar el zip, y crear ALB + Target
Group + Lambda + Security Groups + RDS + ElastiCache. RDS suele tardar
5-10 minutos en quedar disponible.

Al terminar, anota el output `alb_url` (algo como
`http://lab4-alb-123456789.us-east-1.elb.amazonaws.com`).

## 3. Prueba manual rápida

```bash
curl "$(terraform output -raw alb_url)/health"
curl "$(terraform output -raw alb_url)/item/1"          # primera vez -> source: "database"
curl "$(terraform output -raw alb_url)/item/1"          # segunda vez -> source: "cache"
```

Nota: justo después del `apply` puede tardar 10-20s en que el Target Group
marque la Lambda como "healthy"; si el primer curl da error 503, espera un
momento y reintenta.

## 4. Load test con wrk2 (giltene/wrk2)

`wrk2` es una herramienta de C tipo POSIX - en Windows lo más confiable es
compilarla dentro de **WSL** (Windows Subsystem for Linux) o en un
contenedor Docker Linux. Opción WSL (recomendada):

```bash
# dentro de tu distro de WSL (Ubuntu, etc.)
sudo apt update && sudo apt install -y build-essential libssl-dev git zlib1g-dev
git clone https://github.com/giltene/wrk2.git
cd wrk2
make
# esto genera el binario ./wrk
```

Alternativa con Docker (si no quieres instalar WSL):

```bash
docker run --rm -it -v ${PWD}:/wrk2 ubuntu:22.04 bash -c "
  apt update && apt install -y build-essential libssl-dev git zlib1g-dev &&
  git clone https://github.com/giltene/wrk2.git /wrk2/wrk2 &&
  cd /wrk2/wrk2 && make"
```

### Corrida A - "cache NO cargado" (siempre pega a la base de datos)

Usa el parámetro `?fresh=1`, que borra la key de Redis antes de responder,
forzando que cada request vaya a MySQL:

```bash
ALB_URL=$(terraform output -raw alb_url)   # cópialo si corres wrk2 en otra máquina/WSL
./wrk -t4 -c50 -d30s -R100 --latency "${ALB_URL}/item/1?fresh=1"
```

- `-t4`  4 threads
- `-c50` 50 conexiones
- `-R100` 100 requests/seg de throughput constante (ajústalo si tu Lambda/RDS
  no aguanta ese ritmo; wrk2 sigue midiendo la latencia real aunque no
  alcance el rate)
- `-d30s` dura 30 segundos
- `--latency` imprime el histograma de percentiles (p50/p90/p99/p99.999)

Esperado: latencias altas y con más varianza (cada request hace el
`SLEEP(0.15)` + roundtrip a RDS).

### Corrida B - "cache SÍ cargado" (sirve desde Redis)

```bash
curl "${ALB_URL}/item/1"          # 1 sola vez, para precalentar el cache
./wrk -t4 -c50 -d30s -R100 --latency "${ALB_URL}/item/1"
```

Esperado: latencias mucho más bajas y estables (Redis responde en
milisegundos, sin tocar RDS) - esta es la comparación que pide el lab
("performance improvement when cache is not loaded vs when it is loaded").

## 5. Dónde tomar los screenshots para tu PDF

El PDF (`Lab4_706413.pdf` - ajusta el ID si no es el tuyo) lo armas tú;
aquí solo la lista de capturas que te van a pedir según el enunciado:

1. **Consola de AWS mostrando los servicios desplegados**: Lambda
   (`lab4-app`), RDS (`lab4-mysql` -> Available), ElastiCache
   (`lab4-redis` -> Available) y el EC2 > Load Balancers (`lab4-alb`) con
   su Target Group (`lab4-tg`) mostrando el target Lambda como "healthy".
2. **Terminal del `terraform apply`**: desde el comando hasta el bloque
   final `Apply complete! Resources: X added...` con los `Outputs:`
   visibles (alb_url, rds_endpoint, redis_endpoint).
3. **Terminal de la Corrida A (`?fresh=1`, sin cache)**: la salida completa
   de `wrk`, especialmente el bloque `Latency Distribution` y
   `Requests/sec`.
4. **Terminal de la Corrida B (con cache)**: la misma salida de `wrk`, para
   comparar lado a lado contra la Corrida A (idealmente en la misma
   página/slide del PDF, una junto a la otra).
5. Asegúrate de que tu **correo de ITESO** aparezca visible en algún lado
   del PDF (portada o encabezado) y que **la URL de este repo de GitHub**
   esté incluida como texto.

## 6. Limpieza (para no gastar tus créditos del Learner Lab)

```bash
terraform destroy
```

Bórralo cuando ya tengas tus screenshots - RDS y ElastiCache corren todo
el tiempo mientras existan, no solo cuando reciben tráfico.
