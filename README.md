# sistac-dados-ted

Cópia diária dos **TEDs do CNPq** publicados na API aberta do TransfereGov
(`https://api.transferegov.gestao.gov.br/ted`). Os dados são **públicos**.

Este repositório serve de ponte para o SISTAC vNext. Lá, um fluxo do Power Automate
lê estes arquivos com conectores padrão, sem licença Premium.

| Arquivo | Conteúdo |
|---|---|
| `dados/plano_acao.json` | Planos de ação com `sigla_unidade_descentralizada = CNPq` |
| `dados/programa.json` | Programas TED desses planos |
| `dados/termo_execucao.json` | Termos de execução desses planos |

- **Atualização:** GitHub Actions todo dia às 05:30 (Brasília), em `.github/workflows/coleta.yml`. O commit só acontece quando os dados mudam.
- **Script:** `scripts/coleta_ted.py`. Usa só a biblioteca padrão do Python e segue a mesma lógica de `cargaTED()` do sistac.

**Regra:** só dados públicos da API. Nenhuma curadoria, número SEI interno ou dado pessoal entra aqui.
