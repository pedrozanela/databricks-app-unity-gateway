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
