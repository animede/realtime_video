# 公開手順

## 推奨構成

```text
Internet
  -> HTTPS reverse proxy + authentication + rate limit
     -> Realtime Video Studio (127.0.0.1:8781)
        -> internal Vision LLM
        -> internal diffusers-movie-server gateway
        -> internal stem service
```

GPU gateway、LLM、stemサービスのポートはファイアウォールで内部接続だけに制限します。本アプリは任意ファイルのアップロードと高コストなGPU処理を開始できるため、認証なしの公開は避けてください。

## Nginx例

```nginx
server {
    listen 443 ssl http2;
    server_name video.example.com;

    client_max_body_size 100m;

    location / {
        # auth_request、OIDC、Basic認証などを環境に合わせて設定
        limit_req zone=video_generation burst=5 nodelay;
        proxy_pass http://127.0.0.1:8781;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;
        proxy_request_buffering on;
    }
}
```

`limit_req_zone`、TLS証明書、認証設定はNginxのグローバル設定または利用する認証基盤に合わせて追加します。

## 公開前チェックリスト

- `.env`をリポジトリへ含めていない
- LLM APIキーを環境変数またはsecret managerで注入している
- gateway、LLM、stemポートが外部から到達不能
- HTTPSと利用者認証を有効化している
- アップロード上限、要求レート、同時生成数を制限している
- `REALTIME_VIDEO_DATA`を専用ボリュームに置き、容量監視と保存期限を設定している
- 生成物とアップロード画像のプライバシーポリシーを用意している
- `GET /healthz`を監視し、アプリログをローテーションしている
- バックアップ対象は必要な`scenario.json`に限定するか、動画を含む容量を見積もっている

## 更新

生成中でないことをgatewayの状態APIで確認してからアプリを再起動します。Runは`scenario.json`と入力ファイルから復元でき、保存済みシナリオから動画生成を再開できます。
