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
| `dados/convenios.json` | **Lido pelo fluxo F2 do SISTAC.** Convênios do CNPq no SICONV (programas `20501…`), um registro por convênio, com os nomes das colunas da lista `Convenio` e um `HashAPI` |
| `dados/convenios_data_carga.txt` | Data da carga na fonte (Transferegov) |
| `dados/ted.json` | **Lido pelo fluxo do SISTAC.** Os três arquivos acima unidos num registro por plano, com os nomes das colunas da lista `TED` e um `HashAPI` para detectar mudanças. Inclui o PF recebido segundo o Transferegov (`ValorPFRecebido`, `QtdPF`, `FontesRecurso`, `DataUltimaPF`, a partir de `programacao_financeira` + `trf`) |

- **Atualização:** GitHub Actions todo dia às 05:07 (Brasília), com uma execução de reserva às 06:37, em `.github/workflows/coleta.yml`. O commit só acontece quando os dados mudam.
- **Convênios:** `.github/workflows/coleta_convenios.yml`, todo dia às 09:07 (reserva 09:47), depois da atualização da fonte (~08:14), com `scripts/coleta_convenios.py`. Fonte: `https://api-publica.transferegov.gestao.gov.br/downloads/dadosgov/` (substituiu o repositorio.dados.gov.br). Dados bancários e endereço do proponente não entram.
- **Script:** `scripts/coleta_ted.py`. Usa só a biblioteca padrão do Python e segue a mesma lógica de `cargaTED()` do sistac.

**Regra:** só dados públicos da API. Nenhuma curadoria, número SEI interno ou dado pessoal entra aqui.
