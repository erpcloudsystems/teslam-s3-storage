# S3 File Storage Configuration

## Overview
This module enables automatic file uploads to Amazon S3 or S3-compatible storage (like MinIO, DigitalOcean Spaces, etc.) instead of local file storage.

## Configuration

Add the following to your `site_config.json` or `common_site_config.json`:

### AWS S3 Configuration
```json
{
  "use_s3": 1,
  "s3_bucket": "your-bucket-name",
  "s3_region": "us-east-1",
  "s3_access_key_id": "YOUR_ACCESS_KEY_ID",
  "s3_secret_access_key": "YOUR_SECRET_ACCESS_KEY"
}
```

### S3-Compatible Storage (MinIO, DigitalOcean Spaces, etc.)
```json
{
  "use_s3": 1,
  "s3_bucket": "your-bucket-name",
  "s3_region": "us-east-1",
  "s3_access_key_id": "YOUR_ACCESS_KEY_ID",
  "s3_secret_access_key": "YOUR_SECRET_ACCESS_KEY",
  "s3_endpoint_url": "https://your-endpoint.com"
}
```

### With CDN (CloudFront, CloudFlare, etc.)
```json
{
  "use_s3": 1,
  "s3_bucket": "your-bucket-name",
  "s3_region": "us-east-1",
  "s3_access_key_id": "YOUR_ACCESS_KEY_ID",
  "s3_secret_access_key": "YOUR_SECRET_ACCESS_KEY",
  "s3_cdn_url": "https://cdn.yourdomain.com"
}
```

## Configuration Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `use_s3` | Yes | Enable/disable S3 storage (1 or 0) |
| `s3_bucket` | Yes | S3 bucket name |
| `s3_access_key_id` | Yes | AWS Access Key ID or equivalent |
| `s3_secret_access_key` | Yes | AWS Secret Access Key or equivalent |
| `s3_region` | No | AWS region (default: us-east-1) |
| `s3_endpoint_url` | No | Custom endpoint URL for S3-compatible services |
| `s3_cdn_url` | No | CDN URL for serving files |

## How It Works

### File Upload
1. When a file is uploaded to Frappe, the `write_file` hook intercepts the save operation
2. If `use_s3` is enabled and S3 is properly configured, the file is uploaded to S3
3. The file URL is updated to point to the S3 location (or CDN if configured)
4. If S3 upload fails, it falls back to local filesystem storage

### File Deletion
1. When a file is deleted from Frappe, the `delete_file_data_content` hook is called
2. The file is removed from S3 storage
3. Thumbnails are also deleted if present

### Private Files
- Private files are stored in the `private/files/` prefix in S3
- A pre-signed URL valid for 7 days is generated for private files
- Public files are stored in `public/files/` prefix

## Installation

1. Install boto3:
```bash
bench pip install boto3
```

2. Configure S3 in site_config.json

3. Restart bench:
```bash
bench restart
```

## Testing

Upload a file through any Frappe doctype and verify:
1. The file appears in your S3 bucket
2. The file URL in the File doctype points to S3/CDN
3. The file is accessible via the URL
4. Deleting the file also removes it from S3

## Troubleshooting

### Check Error Logs
- Navigate to: Error Log in Frappe
- Look for errors with title "S3 Upload Failed" or "S3 Delete Failed"

### Verify Configuration
```python
import frappe
s3_conf = frappe.conf
print(f"use_s3: {s3_conf.get('use_s3')}")
print(f"s3_bucket: {s3_conf.get('s3_bucket')}")
print(f"s3_region: {s3_conf.get('s3_region')}")
```

### Test S3 Connection
```python
from ecs_s3_storage.utils.s3_file_storage import get_s3_settings, create_s3_client
settings = get_s3_settings()
if settings:
    client = create_s3_client(settings)
    buckets = client.list_buckets()
    print(f"Successfully connected! Buckets: {buckets}")
```

## Security Notes

- Never commit your S3 credentials to version control
- Use IAM roles with minimal required permissions
- For production, consider using AWS IAM roles instead of access keys
- Enable bucket encryption and versioning for production use
- Set appropriate CORS policies on your S3 bucket if accessing from web
