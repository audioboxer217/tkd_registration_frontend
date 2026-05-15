output "config_bucket_name" {
  description = "The name of the Config S3 Bucket."
  value       = aws_s3_bucket.config_bucket.id
}

output "profile_pics_bucket_name" {
  description = "The name of the Profile Pics S3 Bucket."
  value       = aws_s3_bucket.profile-pics_bucket.id
}

output "badges_bucket_name" {
  description = "The name of the Badges S3 Bucket."
  value       = aws_s3_bucket.badges_bucket.id
}

output "public_media_bucket_name" {
  description = "The name of the Public Media S3 Bucket."
  value       = aws_s3_bucket.public_media_bucket.id
}

output "domain_name_servers" {
  description = "The list of name servers for the domain."
  value       = aws_route53_zone.main.name_servers
}

output "domain_zone_id" {
  description = "The Zone ID for the domain."
  value       = aws_route53_zone.main.zone_id
}

output "certificate_arn" {
  description = "The ARN for the ACM Cert."
  value       = aws_acm_certificate.main.arn
}
