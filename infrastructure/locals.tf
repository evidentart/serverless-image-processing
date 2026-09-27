data "aws_caller_identity" "current" {}

locals {
  bucket_name = lower(join("-", [
    var.project_name,
    var.environment,
    data.aws_caller_identity.current.account_id,
  ]))

  lambda_runtime_boundary_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/serverless-image-processing-lambda-boundary"
}
