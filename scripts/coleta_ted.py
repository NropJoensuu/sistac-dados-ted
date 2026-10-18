"""
Coleta os TEDs do CNPq na API pública do TransfereGov e grava JSON em dados/.

Mesma lógica de cargaTED() do sistac (project/ted/services.py): filtra os
planos de ação por sigla_unidade_descentralizada=CNPq no servidor e busca os
programas e termos de execução correspondentes. Só dados públicos da API.
"""

import json
import os
import sys
import urllib.parse
import urllib.request

API_BASE = 'https://api.transferegov.gestao.gov.br/ted'
UNIDADE_CNPQ = 'CNPq'
PASTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'dados')

CAMPOS_PLANO = ','.join([
    'id_plano_acao', 'sq_instrumento', 'aa_instrumento', 'aa_ano_plano_acao', 'id_programa',
    'tx_situacao_plano_acao', 'tx_objeto_plano_acao', 'unidade_descentralizada',
    'vl_beneficiario_especifico', 'vl_chamamento_publico', 'vl_total_plano_acao',
    'dt_inicio_vigencia', 'dt_fim_vigencia',
])
CAMPOS_PROGRAMA = ','.join([
    'id_programa', 'tx_codigo_programa', 'tx_nome_programa',
    'unidade_descentralizadora', 'sigla_unidade_descentralizadora',
])
CAMPOS_TERMO = ','.join([
    'id_plano_acao', 'tx_situacao_termo', 'dt_assinatura_termo',
    'tx_numero_ns_termo', 'tx_num_processo_sei',
])


def consulta(recurso, params):
    url = f'{API_BASE}/{recurso}?{urllib.parse.urlencode(params, safe=",.()")}'
    req = urllib.request.Request(url, headers={'Accept': 'application/json',
                                               'User-Agent': 'sistac-dados-ted'})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def em_lista(ids):
    return 'in.(' + ','.join(str(i) for i in ids) + ')'


def grava(nome, dados, chave):
    # ordena pela chave para o diff diário mostrar só o que mudou de fato
    dados = sorted(dados, key=lambda d: d.get(chave) or 0)
    caminho = os.path.join(PASTA, nome)
    with open(caminho, 'w', encoding='utf-8') as f:
        json.dump(dados, f, ensure_ascii=False, indent=1)
        f.write('\n')
    return len(dados)


def main():
    planos = consulta('plano_acao', {
        'sigla_unidade_descentralizada': f'eq.{UNIDADE_CNPQ}',
        'select': CAMPOS_PLANO,
    })
    if not planos:
        # API fora do ar ou resposta vazia: não sobrescreve os arquivos do dia anterior
        sys.exit('API retornou 0 planos; arquivos mantidos.')

    ids_programa = sorted({p['id_programa'] for p in planos if p.get('id_programa')})
    programas = consulta('programa', {'id_programa': em_lista(ids_programa), 'select': CAMPOS_PROGRAMA})

    ids_plano = sorted(p['id_plano_acao'] for p in planos)
    termos = consulta('termo_execucao', {'id_plano_acao': em_lista(ids_plano), 'select': CAMPOS_TERMO})

    os.makedirs(PASTA, exist_ok=True)
    print('planos:', grava('plano_acao.json', planos, 'id_plano_acao'))
    print('programas:', grava('programa.json', programas, 'id_programa'))
    print('termos:', grava('termo_execucao.json', termos, 'id_plano_acao'))


if __name__ == '__main__':
    main()
