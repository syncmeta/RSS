# 本地备份与恢复

工具针对 Linux Docker、Compose 项目名 `rss`、部署目录 `/opt/rss` 和默认命名卷设计。Python 3.12+；不要在有生产写入的主机上试恢复。

## 备份

把 `export.py` 安装在自己的 RSS 主机 `/usr/local/sbin/rss-backup-export`。它接受 `snapshot` 和指定镜像 ID 的 `images` 请求，输出一致性 SQLite 备份、配置、全文缓存及镜像；需有读取 Docker 数据与运行 Docker 的权限。

在本机执行：

```sh
./deploy/rss-stack/backup/backup-local.sh --host root@rss.example.com --root ./backups/rss
```

使用已核验的 SSH host key。可用 `--identity`、`--known-hosts` 指定独立文件。`--restricted` 仅适用于管理员已配置对应 forced-command SSH 公钥的情形。脚本不安装自动任务；提供的 service/timer 是需要修改主机、路径后自行启用的样例。

快照保留最近 12 次，并补足最近 7 个备份日各一份。镜像按精确 ID 复用。归档包含真实凭据和私人文章，必须放在私人存储，不提交 Git。

## 恢复

```sh
python3.12 deploy/rss-stack/backup/restore.py /path/to/snapshot --images /path/to/images/IMAGE_SET.tar.gz
```

默认只校验散列、数据库和精确镜像 ID。`--prepare` 只能在 `/opt/rss` 及相关命名卷都不存在的新 Linux Docker 主机使用；会恢复配置、镜像与卷，但不启动服务。恢复前先停止旧主机写入并隔离旧 Tunnel，再由管理员检查配置、域名、凭据后手动启动。
