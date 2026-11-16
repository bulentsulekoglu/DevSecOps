global:
  smtp_smarthost: 'smtp.gmail.com:587'
  smtp_from: '__SMTP_FROM__'
  smtp_auth_username: '__SMTP_USER__'
  smtp_auth_password_file: /etc/alertmanager/secrets/smtp_password
  smtp_require_tls: true

route:
  receiver: email
  group_by: ['alertname', 'env']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h

receivers:
  - name: email
    email_configs:
      - to: '__ALERT_TO__'
        send_resolved: true
