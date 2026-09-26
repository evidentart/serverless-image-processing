output "bucket_name" {
  description = "Name of the image storage bucket."
  value       = aws_s3_bucket.images.id
}

output "bucket_arn" {
  description = "ARN of the image storage bucket."
  value       = aws_s3_bucket.images.arn
}

output "upload_api_endpoint" {
  description = "HTTP API endpoint for requesting presigned upload policies."
  value       = aws_apigatewayv2_api.upload.api_endpoint
}
