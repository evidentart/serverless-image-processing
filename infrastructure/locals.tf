data "aws_caller_identity" "current" {}

locals {
  bucket_name = lower(join("-", [
    var.project_name,
    var.environment,
    data.aws_caller_identity.current.account_id,
  ]))
}
