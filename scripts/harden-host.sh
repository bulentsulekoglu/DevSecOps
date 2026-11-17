#!/usr/bin/env bash
set -euo pipefail

# Ubuntu sunucu sertleştirme betiği (idempotent: tekrar çalıştırmak güvenli).
# Kullanım (root olarak):
#   harden-host.sh apply <runner-ip>  değişiklikleri uygular, 10 dk içinde onaylanmazsa
#                                     SSH ve UFW değişikliklerini geri alacak bir zamanlayıcı kurar
#   harden-host.sh confirm            yeni bir SSH bağlantısı doğrulandıktan sonra zamanlayıcıyı iptal eder
#   harden-host.sh rollback           SSH ve UFW değişikliklerini hemen geri alır

[ "$(id -u)" -eq 0 ] || { echo "root olarak çalıştırılmalı (sudo)" >&2; exit 1; }
ACTION="${1:?kullanım: apply <runner-ip> | confirm | rollback}"
SSH_DROPIN=/etc/ssh/sshd_config.d/00-hardening.conf
TIMER=hardening-rollback

case "$ACTION" in
  confirm)
    systemctl stop "$TIMER.timer" 2>/dev/null || true
    systemctl reset-failed 2>/dev/null || true
    echo "Güvenlik zamanlayıcısı iptal edildi, değişiklikler kalıcı."
    exit 0
    ;;
  rollback)
    systemctl stop "$TIMER.timer" 2>/dev/null || true
    ufw disable >/dev/null 2>&1 || true
    rm -f "$SSH_DROPIN"
    systemctl reload ssh
    echo "SSH ve UFW değişiklikleri geri alındı."
    exit 0
    ;;
  apply) ;;
  *)
    echo "bilinmeyen işlem: $ACTION" >&2
    exit 1
    ;;
esac

RUNNER_IP="${2:?runner IP adresi gerekli}"
[[ "$RUNNER_IP" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || { echo "geçersiz IP: $RUNNER_IP" >&2; exit 1; }

# Parola girişini kapatmadan önce anahtarla girişin mümkün olduğundan emin ol
KEY_USER="${SUDO_USER:-}"
if [ -z "$KEY_USER" ] || [ ! -s "/home/$KEY_USER/.ssh/authorized_keys" ]; then
  echo "DURDU: sudo ile çalıştıran kullanıcının authorized_keys dosyası boş ya da yok, kilitlenme riski." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l

echo ">> Güvenlik zamanlayıcısı kuruluyor (10 dk içinde onaylanmazsa SSH ve UFW geri alınır)"
systemctl stop "$TIMER.timer" "$TIMER.service" 2>/dev/null || true
systemd-run --quiet --on-active=10m --unit="$TIMER" \
  /bin/sh -c "ufw disable; rm -f $SSH_DROPIN; systemctl reload ssh"

echo ">> Paketler"
apt-get update -qq
apt-get install -y -qq fail2ban needrestart auditd debsums ufw >/dev/null

mkdir -p /etc/needrestart/conf.d
cat > /etc/needrestart/conf.d/50-list-only.conf <<'CONF'
# Servisleri otomatik yeniden başlatma, sadece listele (Docker kesintisi olmasın)
$nrconf{restart} = 'l';
CONF

echo ">> SSH"
cat > "$SSH_DROPIN" <<'CONF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
MaxAuthTries 3
MaxSessions 2
LoginGraceTime 30
ClientAliveInterval 300
ClientAliveCountMax 2
TCPKeepAlive no
X11Forwarding no
AllowAgentForwarding no
AllowTcpForwarding no
Compression no
LogLevel VERBOSE
CONF
if ! sshd -t; then
  rm -f "$SSH_DROPIN"
  echo "DURDU: sshd yapılandırması geçersiz, değişiklik geri alındı." >&2
  exit 1
fi
systemctl reload ssh

echo ">> fail2ban"
cat > /etc/fail2ban/jail.d/hardening.conf <<CONF
[DEFAULT]
ignoreip = 127.0.0.1/8 ::1 $RUNNER_IP
bantime = 1h
findtime = 10m
maxretry = 5

[sshd]
enabled = true
backend = systemd
CONF
systemctl enable fail2ban >/dev/null 2>&1
systemctl restart fail2ban

echo ">> UFW"
ufw --force reset >/dev/null
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow from "$RUNNER_IP" to any port 22 proto tcp comment 'SSH: runner' >/dev/null
ufw allow from "$RUNNER_IP" to any port 9100 proto tcp comment 'node_exporter: runner' >/dev/null
ufw allow 80/tcp comment 'HTTP' >/dev/null
ufw allow 443/tcp comment 'HTTPS' >/dev/null
ufw --force enable >/dev/null

echo ">> Çekirdek modülleri ve sysctl"
cat > /etc/modprobe.d/hardening.conf <<'CONF'
# Kullanılmayan ağ protokolleri ve USB depolama yüklenmesin
install dccp /bin/false
install sctp /bin/false
install rds /bin/false
install tipc /bin/false
install usb-storage /bin/false
CONF
cat > /etc/sysctl.d/99-hardening.conf <<'CONF'
# net.ipv4.ip_forward bilerek DEĞİŞTİRİLMEDİ: Docker konteyner ağı için 1 olmalı
fs.protected_hardlinks = 1
fs.protected_symlinks = 1
fs.suid_dumpable = 0
kernel.kptr_restrict = 2
kernel.dmesg_restrict = 1
kernel.sysrq = 0
net.core.bpf_jit_harden = 2
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.default.send_redirects = 0
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.default.accept_source_route = 0
net.ipv4.conf.all.log_martians = 1
net.ipv4.conf.default.log_martians = 1
net.ipv4.icmp_echo_ignore_broadcasts = 1
net.ipv4.tcp_syncookies = 1
net.ipv6.conf.all.accept_redirects = 0
net.ipv6.conf.default.accept_redirects = 0
CONF
sysctl --system >/dev/null || echo "UYARI: bazı sysctl değerleri uygulanamadı"

echo ">> Parola yaşı varsayılanları (yeni hesaplar için) ve uyarı metni"
set_login_def() {
  if grep -qE "^$1[[:space:]]" /etc/login.defs; then
    sed -i -E "s/^$1[[:space:]].*/$1\t$2/" /etc/login.defs
  else
    printf '%s\t%s\n' "$1" "$2" >> /etc/login.defs
  fi
}
set_login_def PASS_MAX_DAYS 180
set_login_def PASS_MIN_DAYS 1
set_login_def PASS_WARN_AGE 14
BANNER_TEXT="Yetkisiz erisim yasaktir. Bu sistem izlenmektedir ve tum etkinlikler kayit altina alinir."
printf '%s\n' "$BANNER_TEXT" > /etc/issue
printf '%s\n' "$BANNER_TEXT" > /etc/issue.net

echo ">> auditd"
mkdir -p /etc/docker
cat > /etc/audit/rules.d/hardening.rules <<'CONF'
-w /etc/ssh/sshd_config -p wa -k sshd_config
-w /etc/ssh/sshd_config.d/ -p wa -k sshd_config
-w /etc/passwd -p wa -k identity
-w /etc/shadow -p wa -k identity
-w /etc/group -p wa -k identity
-w /etc/sudoers -p wa -k sudoers
-w /etc/sudoers.d/ -p wa -k sudoers
-w /etc/docker/ -p wa -k docker
-w /var/run/docker.sock -p wa -k docker
CONF
systemctl enable auditd >/dev/null 2>&1
systemctl restart auditd >/dev/null 2>&1 || true
augenrules --load >/dev/null 2>&1 || echo "UYARI: auditd kuralları yüklenemedi"

echo ">> Temizlik (CUPS, eski paketler)"
if systemctl list-unit-files 2>/dev/null | grep -E '^cups' >/dev/null; then
  systemctl disable --now cups.service cups.socket cups.path cups-browsed.service >/dev/null 2>&1 || true
fi
if [ -f /etc/cups/cupsd.conf ]; then chmod 600 /etc/cups/cupsd.conf; fi
rc_pkgs=$(dpkg -l | awk '/^rc/ {print $2}')
if [ -n "$rc_pkgs" ]; then echo "$rc_pkgs" | xargs dpkg --purge >/dev/null; fi

echo
echo ">> Özet"
ufw status verbose | head -14
sshd -T | grep -E '^(passwordauthentication|permitrootlogin|maxauthtries|maxsessions|allowtcpforwarding|x11forwarding|loglevel) '
fail2ban-client status sshd 2>/dev/null | head -4 || true
echo
echo "ŞİMDİ yeni bir terminalden SSH'ı doğrula. 10 dakika içinde 'confirm' çalıştırılmazsa SSH ve UFW otomatik geri alınır."
