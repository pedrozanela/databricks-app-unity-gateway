# Databricks App → Unity Gateway (SP e OBO)

App mínimo (FastAPI) que chama um modelo do **Unity Gateway** de dentro de um Databricks App de duas formas:

| Rota | Autenticação | Token usado |
|---|---|---|
| `/api/sp` | Service principal do App (M2M) | `WorkspaceClient().config.authenticate()` (credenciais `DATABRICKS_CLIENT_ID/SECRET` injetadas pelo Apps) |
| `/api/obo` | On-behalf-of do usuário | header `x-forwarded-access-token` |

A página `/` tem um botão para cada modo e um campo para o model service (`?model=` nas rotas). Ela mostra a resposta, a identidade, o `scope` do token e o `DATABRICKS_HOST` visto pelo App.

## O essencial

```python
from databricks.sdk import WorkspaceClient
from openai import OpenAI

w = WorkspaceClient()
token = w.config.authenticate()["Authorization"].split(" ", 1)[1]  # renova sozinho; pegar a cada request

client = OpenAI(api_key=token, base_url=f"{w.config.host.rstrip('/')}/ai-gateway/mlflow/v1")
client.chat.completions.create(
    model="system.ai.claude-haiku-5-5",  # nome UC de 3 partes
    messages=[{"role": "user", "content": "Diga olá"}],
)
```

- **URL:** `https://<workspace>/ai-gateway/mlflow/v1`. Não use `/serving-endpoints` nem o host regional `*.ai-gateway.*`, que só aceita token `all-apis`.
- **Modelo:** `system.ai.<modelo>` (liste com `databricks ai-gateway list-model-services --parent schemas/system.ai`), e não `databricks-claude-*`.
- **SP:** o token M2M do App sai com scope `all-apis`. O SP precisa de `USE CATALOG` em `system`, `USE SCHEMA` em `system.ai` e `EXECUTE` no model service. `EXECUTE` em `system.ai` vem por padrão para todos os account users, mas pode ter sido revogado por governança. Não precisa de resource `serving_endpoint` no App (`CAN_QUERY` em endpoint não dá acesso ao Unity Gateway).
- **OBO:** adicione o scope `ai-gateway` em *User authorization* do App. Se o App já estava autorizado, abra `https://<app-url>/.auth/sign_out` e reabra o App para refazer o consentimento. Recarregar a página não basta.

## Deploy

```bash
databricks apps create --json '{"name":"gateway-sp-test","user_api_scopes":["ai-gateway"]}'
databricks sync . /Workspace/Users/<voce>/apps/gateway-sp-test
databricks apps deploy gateway-sp-test --source-code-path /Workspace/Users/<voce>/apps/gateway-sp-test
```

Para trocar o modelo, mude `GATEWAY_MODEL` em `app.yaml`.

## "No notebook funciona, no App dá 404"

Reproduzido neste app com um model service customizado (`<catalog>.<schema>.<service>`):

| Quem chama | Grants no service | Resultado |
|---|---|---|
| Usuário (notebook / OBO), owner | todos | ✅ 200 |
| SP do App | nenhum | ❌ `404 - '<catalog>.<schema>.<service>' does not exist.` |
| SP do App | `USE CATALOG` + `USE SCHEMA` | ❌ `403 - User does not have permission to use model service ...` |
| SP do App | + `EXECUTE` | ✅ 200 |

**O 404 não quer dizer que a URL está errada.** O Unity Catalog esconde a existência do objeto de quem não tem acesso. No notebook roda a identidade do usuário (que tem grant); no App roda o SP do App, que é outro principal. Correção, usando o **application ID** do SP (aba *Authorization* do App ou `databricks apps get <app>`):

```bash
databricks grants update catalog <catalog> --json '{"changes":[{"principal":"<sp-app-id>","add":["USE_CATALOG"]}]}'
databricks grants update schema <catalog>.<schema> --json '{"changes":[{"principal":"<sp-app-id>","add":["USE_SCHEMA"]}]}'
databricks grants update model_service <catalog>.<schema>.<service> --json '{"changes":[{"principal":"<sp-app-id>","add":["EXECUTE"]}]}'
```

O mesmo vale para `system.ai.*` se o `EXECUTE` padrão de `account users` tiver sido revogado.

Outras fontes de 404 testadas:
- `model` com nome legado: `system.ai.databricks-claude-haiku-5-5` dá 404. O nome do model service é `system.ai.claude-haiku-5-5`. O nome com `databricks-` é o do *modelo* UC usado como destino na criação de um service customizado.
- `/serving-endpoints/...` com nome UC (`system.ai.*`) dá `ENDPOINT_NOT_FOUND`.
- Path relativo (`fetch('/ai-gateway/...')` no frontend) cai no host do App (`*.databricksapps.com`) e dá `{"detail":"Not Found"}`.

Não dá 404, mas é armadilha: no Apps, `DATABRICKS_HOST` vem **sem `https://`**. Usar o valor cru no `base_url` dá `APIConnectionError` / `UnsupportedProtocol`. Use `WorkspaceClient().config.host`, que já vem normalizado.

## Se der erro

| Mensagem | Causa provável |
|---|---|
| `required scopes: ...` | Token sem o scope certo: OBO sem `ai-gateway`, ou uso do host regional `*.ai-gateway.*` |
| `PERMISSION_DENIED` com `EXECUTE` / `USE CATALOG` | Faltam grants no UC para o SP/usuário |
| `Querying pay-per-token foundation model endpoint ... Please use Unity Gateway` | Ainda está chamando `/serving-endpoints/databricks-*` |
| `404 ... does not exist` | SP/usuário sem `EXECUTE` (o UC responde 404, ver acima) ou nome de model service errado |
| Modelo indisponível | Preview *Enhanced Unity Gateway* não habilitado na account (no Azure é opt-in), ou modelo não servido na região do workspace (cross-geo) |
