#!/bin/bash
set -e

dnf update -y
dnf install -y httpd

systemctl enable httpd
systemctl start httpd

HOSTNAME=$(hostname)
cat <<HTML > /var/www/html/index.html
<html>
<head><title>Lab1 Backend</title></head>
<body>
<h1>Backend funcionando</h1>
<p>Hostname: ${HOSTNAME}</p>
</body>
</html>
HTML
