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
| `dados/ted.json` | **Lido pelo fluxo do SISTAC.** Os três arquivos acima unidos num registro por plano, com os nomes das colunas da lista `TED` e um `HashAPI` para detectar mudanças |

- **Atualização:** GitHub Actions todo dia às 05:07 (Brasília), com uma execução de reserva às 06:37, em `.github/workflows/coleta.yml`. O commit só acontece quando os dados mudam.
- **Script:** `scripts/coleta_ted.py`. Usa só a biblioteca padrão do Python e segue a mesma lógica de `cargaTED()` do sistac.

**Regra:** só dados públicos da API. Nenhuma curadoria, número SEI interno ou dado pessoal entra aqui.
