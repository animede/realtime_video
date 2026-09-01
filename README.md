# Realtime Video Studio

キャラクター画像と物語の方向性から、Vision LLMでシナリオとシーンプロンプトを作成し、LTX-2.5の動画を生成しながら連続再生するFastAPIアプリです。

## 主な機能

- キャラクター画像、音楽、複数のシーン参照画像を1か所からD&D
- LLMによる画像解析、シナリオ分割、シーンプロンプト生成
- 16 / 20 / 24fps、横型・4:3・縦型プロファイル
- 最終フレームを次シーンへ渡す連続生成
- 元音楽をマスタークロックにした途切れない再生
- ボーカル分離による無歌唱区間の口運動抑制
- 同じシナリオからプロファイルを変更して繰り返し生成
- シナリオJSONの自動保存、ブラウザー復元、ダウンロード

## 必要なサービス

- Python 3.11以上と`ffmpeg` / `ffprobe`
- diffusers-movie-server gateway
- OpenAI互換のVision LLM（未設定時は簡易フォールバックシナリオ）
- ボーカル解析を使う場合はMinimax-H3-lipsync-mv互換環境とstem分離サービス

gateway、LLM、stemサービスは内部ネットワークに置き、インターネットへ直接公開しないでください。

## セットアップ

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
cp .env.example .env
```

`.env`に実環境の内部URLとパスを設定して起動します。

```bash
./run.sh
```

既定では`127.0.0.1:8781`だけで待ち受けます。ローカルでは`http://localhost:8781`を開きます。

## 環境変数

| 変数 | 用途 | 既定値 |
|---|---|---|
| `HOST` | Web待受アドレス | `127.0.0.1` |
| `PORT` | Web待受ポート | `8781` |
| `GATEWAY_URL` | 内部gateway URL | `http://127.0.0.1:8630` |
| `GATEWAY_PRESET` | LTXロードプリセット | `nvfp4-fast` |
| `VISION_LLM_URL` | OpenAI互換chat completions URL | 未設定 |
| `VISION_LLM_MODEL` | モデル名。空なら`/v1/models`から選択 | 未設定 |
| `VISION_LLM_API_KEY` | LLM認証キー | 未設定 |
| `REALTIME_VIDEO_DATA` | アップロード・動画・シナリオ保存先 | `./data` |
| `JOB_POLL_INTERVAL` | gatewayポーリング秒数 | `0.35` |
| `LIPSYNC_APP_DIR` | lipsync連携コードのルート | 隣接リポジトリを探索 |
| `VOCAL_ANALYSIS_PYTHON` | librosaと連携コードを実行するPython | 連携環境または現在のPython |
| `STEM_API_URL` | stem分離サービスURL | `http://127.0.0.1:8889` |
| `DEMUCS_PYTHON` | ローカルDemucs用Python | 存在する隣接環境を探索 |

`.env`はGit管理対象外です。APIキーや公開IPをコード、README、シナリオJSONへ書かないでください。

## 公開

本アプリを直接インターネットへbindせず、TLSと認証を設定したリバースプロキシの背後で動かしてください。設定例とチェックリストは[公開手順](docs/deployment.md)を参照してください。

## テスト

```bash
pip install -e '.[dev]'
pytest -q
curl -f http://127.0.0.1:8781/healthz
```

性能測定結果は[`docs/`](docs/)にあります。

## ライセンス

本アプリのソースコードはApache License 2.0で提供します。詳細と第三者コンポーネントの区分は[LICENSE](LICENSE)と[NOTICE](NOTICE)を参照してください。

この表記はモデル重みには適用されません。LTX-2/LTX-2.5、MiniMax-H3、Gemma、LoRA、その他のモデルやライブラリには、それぞれの配布元が定めるライセンスと利用条件が適用されます。
