locals {
  common_tags = {
    "TF_Workspace" = var.TFC_WORKSPACE_NAME
    "Terraform"    = "true"
  }
}
