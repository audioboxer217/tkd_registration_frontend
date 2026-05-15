resource "aws_s3_bucket" "profile-pics_bucket" {
  bucket              = var.profile_pics_bucket_name == "" ? null : var.profile_pics_bucket_name
  bucket_prefix       = var.profile_pics_bucket_name != "" ? null : var.profile_pics_bucket_prefix
  force_destroy       = null
  object_lock_enabled = false
  tags                = local.common_tags
}

resource "aws_s3_bucket_versioning" "profile-pics_bucket" {
  bucket = aws_s3_bucket.profile-pics_bucket.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket" "badges_bucket" {
  bucket              = var.badges_bucket_name == "" ? null : var.badges_bucket_name
  bucket_prefix       = var.badges_bucket_name != "" ? null : var.badges_bucket_prefix
  force_destroy       = null
  object_lock_enabled = false
  tags                = local.common_tags
}

resource "aws_s3_bucket_versioning" "badges_bucket" {
  bucket = aws_s3_bucket.badges_bucket.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket" "config_bucket" {
  bucket              = var.config_bucket_name == "" ? null : var.config_bucket_name
  bucket_prefix       = var.config_bucket_name != "" ? null : var.config_bucket_prefix
  force_destroy       = null
  object_lock_enabled = false
  tags                = local.common_tags
}

resource "aws_s3_bucket_versioning" "config_bucket" {
  bucket = aws_s3_bucket.config_bucket.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket" "public_media_bucket" {
  bucket              = var.public_media_bucket_name == "" ? null : var.public_media_bucket_name
  bucket_prefix       = var.public_media_bucket_name != "" ? null : var.public_media_bucket_prefix
  force_destroy       = null
  object_lock_enabled = false
  tags                = local.common_tags
}

resource "aws_s3_bucket_versioning" "public_media_bucket" {
  bucket = aws_s3_bucket.public_media_bucket.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_route53_zone" "main" {
  name = var.domain_name
  tags = local.common_tags
}

resource "aws_acm_certificate" "main" {
  domain_name               = var.domain_name
  key_algorithm             = "RSA_2048"
  subject_alternative_names = [var.domain_name]
  validation_method         = "DNS"
  options {
    certificate_transparency_logging_preference = "ENABLED"
  }
  tags = local.common_tags
}

resource "aws_route53_record" "validation" {
  for_each = {
    for dvo in aws_acm_certificate.main.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  }

  allow_overwrite = true
  name            = each.value.name
  records         = [each.value.record]
  ttl             = 60
  type            = each.value.type
  zone_id         = aws_route53_zone.main.zone_id
}

resource "aws_acm_certificate_validation" "main" {
  certificate_arn         = aws_acm_certificate.main.arn
  validation_record_fqdns = [for record in aws_route53_record.validation : record.fqdn]
}
