output "bucket_name" {
  description = "Name of the image storage bucket."
  value       = aws_s3_bucket.images.id
}

output "bucket_arn" {
  description = "ARN of the image storage bucket."
  value       = aws_s3_bucket.images.arn
}
