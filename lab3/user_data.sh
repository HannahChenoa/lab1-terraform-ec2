#!/bin/bash
set -e

dnf update -y
dnf install -y httpd

systemctl enable httpd
systemctl start httpd

TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
PRIVATE_IP=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/local-ipv4)
INSTANCE_ID=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/instance-id)
AZ=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/placement/availability-zone)

cat <<HTML > /var/www/html/index.html
<html>
<head>
<title>Lab3 - Autoscaling</title>
<style>
  body { font-family: 'Segoe UI', Arial, sans-serif; background: linear-gradient(135deg,#0f172a,#1e293b); color:#e2e8f0; display:flex; align-items:center; justify-content:center; height:100vh; margin:0; }
  .card { background:#1e293b; padding:2.5rem 3.5rem; border-radius:16px; box-shadow:0 8px 24px rgba(0,0,0,.5); text-align:center; border:1px solid #334155; }
  h1 { color:#a78bfa; margin:0 0 1.5rem 0; font-size:1.8rem; }
  .row { margin-top:1rem; padding-top:1rem; border-top:1px solid #334155; }
  .row:first-of-type { border-top:none; padding-top:0; margin-top:0; }
  .label { color:#94a3b8; font-size:0.75rem; text-transform:uppercase; letter-spacing:0.08em; }
  .value { font-size:1.3rem; font-weight:700; color:#f1f5f9; margin-top:0.25rem; }
  .badge { display:inline-block; margin-top:1.5rem; background:#a78bfa; color:#1e0f3d; padding:0.35rem 1rem; border-radius:999px; font-size:0.8rem; font-weight:700; }
</style>
</head>
<body>
  <div class="card">
    <h1>Instancia Autoscaling</h1>
    <div class="row">
      <div class="label">Instance ID</div>
      <div class="value">$INSTANCE_ID</div>
    </div>
    <div class="row">
      <div class="label">Private IP</div>
      <div class="value">$PRIVATE_IP</div>
    </div>
    <div class="row">
      <div class="label">Availability Zone</div>
      <div class="value">$AZ</div>
    </div>
    <div class="badge">Lab 3 · Auto Scaling Group</div>
  </div>
</body>
</html>
HTML
