output "instance_id" {
  description = "ID de la instancia EC2"
  value       = aws_instance.lab1.id
}

output "public_ip" {
  description = "IP pública de la instancia EC2"
  value       = aws_instance.lab1.public_ip
}

output "public_dns" {
  description = "DNS público de la instancia EC2"
  value       = aws_instance.lab1.public_dns
}

output "ssh_command" {
  description = "Comando para conectarte por SSH"
  value       = "ssh -i ${var.key_name}.pem ec2-user@${aws_instance.lab1.public_ip}"
}

output "backend_url" {
  description = "URL para probar que el backend (httpd) está corriendo"
  value       = "http://${aws_instance.lab1.public_dns}"
}
