"""
Coleta os TEDs do CNPq na API pública do TransfereGov e grava JSON em dados/.

Mesma lógica de cargaTED() do sistac (project/ted/services.py): filtra os
planos de ação por sigla_unidade_descentralizada=CNPq no servidor e busca os
programas e termos de execução correspondentes. Só dados públicos da API.
"""

import hashlib
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
    print('ted:', grava('ted.json', une_ted(planos, programas, termos), 'IdPlanoAcao'))


def une_ted(planos, programas, termos):
    """
    Junta plano + programa + termo num registro por plano de ação, já com os
    nomes das colunas da lista TED do SharePoint (docs/03-mvp-ted.md §4.4 do
    sistac-vnext). Assim o fluxo do Power Automate só lê um arquivo e não
    precisa cruzar as três tabelas. `HashAPI` permite ao fluxo atualizar só
    os itens que mudaram.
    """
    prog_por_id = {p['id_programa']: p for p in programas}
    termo_por_plano = {t['id_plano_acao']: t for t in termos}  # 1:1 (v0.3)
    registros = []
    for p in planos:
        prog = prog_por_id.get(p.get('id_programa'), {})
        termo = termo_por_plano.get(p['id_plano_acao'], {})
        if p.get('sq_instrumento'):
            rotulo = f"TED {p['sq_instrumento']}/{p.get('aa_instrumento') or ''}".rstrip('/')
        else:
            rotulo = f"Plano {p['id_plano_acao']} (sem número)"
        reg = {
            'Title': rotulo,
            'IdPlanoAcao': p['id_plano_acao'],
            'NumeroTED': p.get('sq_instrumento'),
            'AnoInstrumento': p.get('aa_instrumento'),
            'Ano': p.get('aa_ano_plano_acao'),
            'SituacaoPlano': p.get('tx_situacao_plano_acao'),
            'Objeto': p.get('tx_objeto_plano_acao'),
            'UnidadeDescentralizada': p.get('unidade_descentralizada'),
            'ValorBeneficiarioEspecifico': p.get('vl_beneficiario_especifico'),
            'ValorChamamentoPublico': p.get('vl_chamamento_publico'),
            'ValorTotal': p.get('vl_total_plano_acao'),
            'VigenciaInicio': p.get('dt_inicio_vigencia'),
            'VigenciaFim': p.get('dt_fim_vigencia'),
            'IdProgramaTED': p.get('id_programa'),
            'CodigoProgramaTED': prog.get('tx_codigo_programa'),
            'NomeProgramaTED': prog.get('tx_nome_programa'),
            'UnidadeDescentralizadora': prog.get('unidade_descentralizadora'),
            'SiglaUnidadeDescentralizadora': prog.get('sigla_unidade_descentralizadora'),
            'SituacaoTermo': termo.get('tx_situacao_termo'),
            'DataAssinatura': termo.get('dt_assinatura_termo'),
            'NumeroNSTermo': termo.get('tx_numero_ns_termo'),
            'ReferenciaExterna': termo.get('tx_num_processo_sei'),
        }
        # A API já trouxe data com ano inválido (DataAssinatura "0232-12-21" no
        # plano 1876, em 2026-10-18) e o SharePoint recusa datas antes de 1900.
        # Data fora da faixa vira vazia e o valor original fica em AvisoDados.
        avisos = []
        for campo in ('VigenciaInicio', 'VigenciaFim', 'DataAssinatura'):
            valor = reg[campo]
            if valor and not ('1900' <= valor[:4] <= '2100'):
                avisos.append(f'{campo} inválida na API: {valor}')
                reg[campo] = None
        reg['AvisoDados'] = '; '.join(avisos) or None
        reg['HashAPI'] = hashlib.sha1(json.dumps(reg, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        registros.append(reg)
    return registros


if __name__ == '__main__':
    main()
