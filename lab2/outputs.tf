output "instance_ids" {
  description = "IDs de las 2 instancias EC2"
  value       = aws_instance.web[*].id
}

output "instance_private_ips" {
  description = "IPs privadas de las 2 instancias EC2"
  value       = aws_instance.web[*].private_ip
}

output "instance_public_ips" {
  description = "IPs públicas de las 2 instancias EC2"
  value       = aws_instance.web[*].public_ip
}

output "alb_dns_name" {
  description = "DNS público del Application Load Balancer"
  value       = aws_lb.app.dns_name
}

output "alb_url_https" {
  description = "URL HTTPS del load balancer (certificado autofirmado - el navegador va a mostrar advertencia, dale avanzar/continuar)"
  value       = "https://${aws_lb.app.dns_name}"
}

output "alb_url_http" {
  description = "Esta URL redirige automáticamente a HTTPS"
  value       = "http://${aws_lb.app.dns_name}"
}
