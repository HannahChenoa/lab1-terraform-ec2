output "alb_dns_name" {
  description = "DNS público del Application Load Balancer"
  value       = aws_lb.app.dns_name
}

output "alb_url" {
  description = "URL para probar el load balancer (refresca para ver distintas instancias respondiendo)"
  value       = "http://${aws_lb.app.dns_name}"
}

output "autoscaling_group_name" {
  description = "Nombre del Auto Scaling Group"
  value       = aws_autoscaling_group.web.name
}

output "launch_template_id" {
  description = "ID del launch template usado por el ASG"
  value       = aws_launch_template.web.id
}
