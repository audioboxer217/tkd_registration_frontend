variable "TFC_WORKSPACE_NAME" {
  type        = string
  description = "The name of the workspace in Terraform Cloud where this is managed."
  default     = ""
}

variable "domain_name" {
  type        = string
  description = "The domain to use for this site."
}

variable "profile_pics_bucket_name" {
  type        = string
  description = "The name to use for bucket that will hold the Profile Pics (Overrides `profile_pics_bucket_prefix` if provided)."
  default     = ""
}

variable "profile_pics_bucket_prefix" {
  type        = string
  description = "The prefix to use for bucket that will hold the Profile Pics."
  default     = "tkd-reg-profile-pics"
}

variable "badges_bucket_name" {
  type        = string
  description = "The name to use for bucket that will hold the Badges (Overrides `badges_bucket_prefix` if provided)."
  default     = ""
}

variable "badges_bucket_prefix" {
  type        = string
  description = "The prefix to use for bucket that will hold the Badges."
  default     = "tkd-reg-badges"
}

variable "config_bucket_name" {
  type        = string
  description = "The name to use for bucket that will hold the Configs (Overrides `config_bucket_prefix` if provided)."
  default     = ""
}

variable "config_bucket_prefix" {
  type        = string
  description = "The prefix to use for bucket that will hold the Configs."
  default     = "tkd-reg-config"
}

variable "public_media_bucket_name" {
  type        = string
  description = "The name to use for bucket that will hold the public media (Overrides `public_media_bucket_prefix` if provided)."
  default     = ""
}

variable "public_media_bucket_prefix" {
  type        = string
  description = "The prefix to use for bucket that will hold the public media."
  default     = "tkd-reg-public-media"
}
