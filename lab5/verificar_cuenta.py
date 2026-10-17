"""
Revisa TODA la cuenta del Learner Lab (no solo el lab5) y lista lo que sigue
prendido y puede estar gastando presupuesto: también encuentra sobras de labs
anteriores.

  python verificar_cuenta.py

Solo lee; no borra nada.
"""
import sys

import boto3
from botocore.exceptions import BotoCoreError, ClientError

REGIONES = ["us-east-1", "us-west-2"]  # las que habilita el Learner Lab

try:
    sesion = boto3.Session(profile_name="academy")
except Exception:
    sesion = boto3.Session()


def revisar(region):
    c = lambda s: sesion.client(s, region_name=region)  # noqa: E731
    hallazgos = []

    def chequeo(nombre, fn):
        try:
            for linea in fn():
                hallazgos.append(f"{nombre}: {linea}")
        except (ClientError, BotoCoreError) as e:
            codigo = getattr(e, "response", {}).get("Error", {}).get("Code", type(e).__name__)
            if codigo in ("ExpiredToken", "ExpiredTokenException", "UnrecognizedClientException"):
                sys.exit("Credenciales vencidas: vuelve a pegarlas del Learner Lab en el profile academy.")
            # Servicios sin permiso en el lab se ignoran

    ec2 = c("ec2")
    chequeo("EC2 instancia", lambda: [
        f"{i['InstanceId']} {i['InstanceType']} ({i['State']['Name']})"
        for r in ec2.describe_instances(Filters=[{"Name": "instance-state-name",
                                                  "Values": ["pending", "running", "stopping", "stopped"]}])["Reservations"]
        for i in r["Instances"]])
    chequeo("EBS volumen suelto", lambda: [
        f"{v['VolumeId']} {v['Size']} GB"
        for v in ec2.describe_volumes(Filters=[{"Name": "status", "Values": ["available"]}])["Volumes"]])
    chequeo("Elastic IP", lambda: [
        f"{a['PublicIp']}" + ("" if a.get("AssociationId") else " (sin usar: cobra)")
        for a in ec2.describe_addresses()["Addresses"]])
    chequeo("NAT Gateway", lambda: [
        n["NatGatewayId"] for n in ec2.describe_nat_gateways(
            Filters=[{"Name": "state", "Values": ["pending", "available"]}])["NatGateways"]])
    chequeo("Load balancer", lambda: [
        f"{lb['LoadBalancerName']} ({lb['Type']})" for lb in c("elbv2").describe_load_balancers()["LoadBalancers"]])
    chequeo("RDS", lambda: [
        f"{d['DBInstanceIdentifier']} {d['DBInstanceClass']} ({d['DBInstanceStatus']})"
        for d in c("rds").describe_db_instances()["DBInstances"]])
    chequeo("RDS snapshot manual", lambda: [
        s["DBSnapshotIdentifier"] for s in c("rds").describe_db_snapshots(SnapshotType="manual")["DBSnapshots"]])
    chequeo("Kinesis stream", lambda: c("kinesis").list_streams()["StreamNames"])
    chequeo("EKS cluster", lambda: c("eks").list_clusters()["clusters"])
    chequeo("ECS servicio", lambda: [
        s for cl in c("ecs").list_clusters()["clusterArns"]
        for s in c("ecs").list_services(cluster=cl)["serviceArns"]])
    chequeo("ElastiCache", lambda: [
        cc["CacheClusterId"] for cc in c("elasticache").describe_cache_clusters()["CacheClusters"]])
    chequeo("SageMaker notebook", lambda: [
        f"{n['NotebookInstanceName']} ({n['NotebookInstanceStatus']})"
        for n in c("sagemaker").list_notebook_instances()["NotebookInstances"]
        if n["NotebookInstanceStatus"] != "Stopped"])
    chequeo("SageMaker endpoint", lambda: [
        e["EndpointName"] for e in c("sagemaker").list_endpoints()["Endpoints"]])
    chequeo("Redshift Serverless workgroup", lambda: [
        f"{w['workgroupName']} ({w['status']}, base {w.get('baseCapacity')} RPU)"
        for w in c("redshift-serverless").list_workgroups()["workgroups"]])
    chequeo("Redshift cluster", lambda: [
        f"{cl['ClusterIdentifier']} {cl['NodeType']} ({cl['ClusterStatus']})"
        for cl in c("redshift").describe_clusters()["Clusters"]])
    chequeo("API Gateway con cache", lambda: [
        f"{api['name']} / stage {st['stageName']} (cache {st.get('cacheClusterSize')} GB)"
        for api in c("apigateway").get_rest_apis()["items"]
        for st in c("apigateway").get_stages(restApiId=api["id"])["item"]
        if st.get("cacheClusterEnabled")])
    chequeo("Managed Grafana workspace", lambda: [
        w["name"] for w in c("grafana").list_workspaces()["workspaces"]])
    return hallazgos


total = 0
for region in REGIONES:
    h = revisar(region)
    total += len(h)
    print(f"\n== {region} ==")
    print("\n".join(f"  ⚠️  {x}" for x in h) if h else "  ✅ nada que cobre por hora")

print("\nNo se revisan: S3 (casi no cobra) ni Lambda/SQS/API Gateway sin cache (cobran solo por uso).")
if total:
    print(f"\nHay {total} recurso(s) prendidos. Si son de otro lab, entra a esa carpeta y corre "
          "`terraform destroy`, o bórralos desde la consola.")
    sys.exit(1)
