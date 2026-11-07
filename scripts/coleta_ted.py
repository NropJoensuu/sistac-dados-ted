"""
Coleta os TEDs do CNPq na API pública do TransfereGov e grava JSON em dados/.

Mesma lógica de cargaTED() do sistac (project/ted/services.py): filtra os
planos de ação por sigla_unidade_descentralizada=CNPq no servidor e busca os
programas e termos de execução correspondentes. Só dados públicos da API.

Desde a ADR 0009 (passo c), grava também o detalhe das notas de crédito
(ted_nc.json, uma linha por evento) e das programações financeiras (ted_pf.json).
"""

import hashlib
import json
import os
import sys
import time
import urllib.error
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

CAMPOS_PF = ','.join([
    'id_programacao', 'id_plano_acao', 'tx_numero_programacao', 'tx_situacao_programacao',
    'dh_recebimento_programacao', 'ug_emitente_programacao', 'ug_favorecida_programacao',
])
CAMPOS_TRF = ','.join([
    'id_programacao', 'cd_fonte_recurso_trf', 'cd_categoria_gasto_trf',
    'cd_situacao_contabil_trf', 'vl_valor_trf',
])
CAMPOS_NC = ','.join([
    'id_nota', 'id_plano_acao', 'tx_numero_nota', 'dt_emissao_nota', 'tx_situacao_nota',
    'cd_ug_emitente_nota', 'cd_gestao_emitente_nota',
    'cd_ug_favorecida_nota', 'cd_gestao_favorecida_nota',
])
CAMPOS_EVENTO = ','.join([
    'id_nota', 'cd_evento', 'codigo_natureza', 'descricao_natureza',
    'cd_fonte_recurso_evento', 'cd_plano_interno_evento', 'cd_ptres_evento',
    'cd_ug_responsavel_evento', 'nome_esfera_orcamentaria', 'vl_evento',
])

# tx_observacao_nota e tx_observacao_programacao ficam de fora de propósito: são texto
# livre e trazem nomes de pessoas, e este repositório é público (ADR 0009, critério 2).

TENTATIVAS = 4


PAGINA = 1000  # a API (PostgREST) devolve no máximo 1.000 linhas por chamada


def consulta(recurso, params):
    """Busca todas as páginas do recurso (limit/offset)."""
    dados, offset = [], 0
    while True:
        pagina = _chamada(recurso, dict(params, limit=PAGINA, offset=offset))
        dados += pagina
        if len(pagina) < PAGINA:
            return dados
        offset += PAGINA


def em_lotes(recurso, campo, ids, select, tamanho=150):
    """Consulta `campo=in.(...)` em lotes, para não estourar o tamanho da URL."""
    dados = []
    for i in range(0, len(ids), tamanho):
        dados += consulta(recurso, {campo: em_lista(ids[i:i + tamanho]), 'select': select})
    return dados


def _chamada(recurso, params):
    url = f'{API_BASE}/{recurso}?{urllib.parse.urlencode(params, safe=",.()")}'
    req = urllib.request.Request(url, headers={'Accept': 'application/json',
                                               'User-Agent': 'sistac-dados-ted'})
    # a API do TransfereGov oscila (timeout, 502/503); tenta de novo com espera
    # crescente antes de desistir, para uma instabilidade curta não custar o dia
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as erro:
            if tentativa == TENTATIVAS:
                raise
            espera = 30 * tentativa
            print(f'{recurso}: falha na tentativa {tentativa} ({erro}); nova tentativa em {espera}s')
            time.sleep(espera)


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

    # financeiro recebido (PF): programações financeiras do plano + valores e fontes (trf)
    programacoes = em_lotes('programacao_financeira', 'id_plano_acao', ids_plano, CAMPOS_PF)
    ids_pf = sorted(pf['id_programacao'] for pf in programacoes)
    repasses = em_lotes('trf', 'id_programacao', ids_pf, CAMPOS_TRF)

    # notas de crédito do plano + eventos (detalhe orçamentário de cada nota)
    notas = em_lotes('nota_credito', 'id_plano_acao', ids_plano, CAMPOS_NC)
    ids_nota = sorted(n['id_nota'] for n in notas)
    eventos = em_lotes('evento', 'id_nota', ids_nota, CAMPOS_EVENTO)

    os.makedirs(PASTA, exist_ok=True)
    print('planos:', grava('plano_acao.json', planos, 'id_plano_acao'))
    print('programas:', grava('programa.json', programas, 'id_programa'))
    print('termos:', grava('termo_execucao.json', termos, 'id_plano_acao'))
    print('programações financeiras:', len(programacoes), '| repasses:', len(repasses))
    print('notas de crédito:', len(notas), '| eventos:', len(eventos))
    print('ted:', grava('ted.json', une_ted(planos, programas, termos, programacoes, repasses, notas), 'IdPlanoAcao'))
    print('ted_nc:', grava('ted_nc.json', linhas_nc(notas, eventos), 'Title'))
    print('ted_pf:', grava('ted_pf.json', linhas_pf(programacoes, repasses), 'Title'))


def une_ted(planos, programas, termos, programacoes=(), repasses=(), notas=()):
    """
    Junta plano + programa + termo num registro por plano de ação, já com os
    nomes das colunas da lista TED do SharePoint (docs/03-mvp-ted.md §4.4 do
    sistac-vnext). Assim o fluxo do Power Automate só lê um arquivo e não
    precisa cruzar as três tabelas. `HashAPI` permite ao fluxo atualizar só
    os itens que mudaram.
    """
    prog_por_id = {p['id_programa']: p for p in programas}
    termo_por_plano = {t['id_plano_acao']: t for t in termos}  # 1:1 (v0.3)
    fin = _financeiro(programacoes, repasses)
    nc = _resumo_nc(notas)
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
            **fin.get(p['id_plano_acao'], VAZIO_FIN),
            **nc.get(p['id_plano_acao'], VAZIO_NC),
        }
        for campo in ('DataUltimaPF', 'DataUltimaNC'):
            if reg[campo] and not _data_valida(reg[campo]):
                reg[campo] = None
        # A API já trouxe data com ano inválido (DataAssinatura "0232-12-21" no
        # plano 1876, em 2026-10-18) e o SharePoint recusa datas antes de 1900.
        # Data fora da faixa vira vazia e o valor original fica em AvisoDados.
        avisos = []
        for campo in ('VigenciaInicio', 'VigenciaFim', 'DataAssinatura'):
            valor = reg[campo]
            if valor and not _data_valida(valor):
                avisos.append(f'{campo} inválida na API: {valor}')
                reg[campo] = None
        reg['AvisoDados'] = '; '.join(avisos) or None
        registros.append(_com_hash(reg))
    return registros


def _data_valida(valor):
    return '1900' <= valor[:4] <= '2100'


def _com_hash(reg):
    reg['HashAPI'] = hashlib.sha1(json.dumps(reg, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return reg


def _data(valor, campo, avisos):
    """Data ISO (AAAA-MM-DD); fora da faixa do SharePoint vira vazia e vai para o aviso."""
    if not valor:
        return None
    if not _data_valida(valor):
        avisos.append(f'{campo} inválida na API: {valor}')
        return None
    return valor[:10]


def _distintos(valores):
    # a API mistura trf003/TRF003 e traz espaço sobrando
    return ', '.join(sorted({v.strip().upper() for v in valores if v and v.strip()})) or None


def _ug(ug, gestao):
    return '/'.join(v for v in (ug, gestao) if v) or None


def _chave_evento(e):
    """Ordem estável dos eventos dentro da nota; define o n da chave {id_nota}-{n}."""
    return tuple(str(e.get(c) or '') for c in ('cd_evento', 'codigo_natureza', 'cd_fonte_recurso_evento',
                                               'cd_plano_interno_evento', 'cd_ptres_evento')) + (e.get('vl_evento') or 0,)


def linhas_nc(notas, eventos):
    """
    Uma linha por evento da nota de crédito (lista TED_NotaCredito, ADR 0009 item C).
    Nota sem evento vira uma linha com os campos de evento vazios. Não há total de
    NC: o sentido dos códigos de evento ainda depende de confirmação da COPES.
    """
    por_nota = {}
    for e in eventos:
        por_nota.setdefault(e['id_nota'], []).append(e)
    linhas = []
    for nota in notas:
        for n, e in enumerate(sorted(por_nota.get(nota['id_nota'], []), key=_chave_evento) or [{}], 1):
            avisos = []
            natureza = ' – '.join(v for v in (e.get('codigo_natureza'), e.get('descricao_natureza')) if v) or None
            reg = {
                'Title': f"{nota['id_nota']}-{n}",
                'IdPlanoAcao': nota['id_plano_acao'],
                'IdNota': nota['id_nota'],
                'NumeroNC': nota.get('tx_numero_nota'),
                'DataEmissao': _data(nota.get('dt_emissao_nota'), 'DataEmissao', avisos),
                'SituacaoNC': nota.get('tx_situacao_nota'),
                'UGEmitente': _ug(nota.get('cd_ug_emitente_nota'), nota.get('cd_gestao_emitente_nota')),
                'UGFavorecida': _ug(nota.get('cd_ug_favorecida_nota'), nota.get('cd_gestao_favorecida_nota')),
                'CodigoEvento': e.get('cd_evento'),
                'NaturezaDespesa': natureza,
                'FonteRecurso': e.get('cd_fonte_recurso_evento'),
                'PlanoInterno': e.get('cd_plano_interno_evento'),
                'PTRES': e.get('cd_ptres_evento'),
                'UGResponsavel': e.get('cd_ug_responsavel_evento'),
                'EsferaOrcamentaria': e.get('nome_esfera_orcamentaria'),
                'Valor': e.get('vl_evento'),
            }
            reg['AvisoDados'] = '; '.join(avisos) or None
            linhas.append(_com_hash(reg))
    return linhas


def linhas_pf(programacoes, repasses):
    """Uma linha por programação financeira (lista TED_PF, ADR 0009 item C); os trf entram somados."""
    por_pf = {}
    for t in repasses:
        por_pf.setdefault(t['id_programacao'], []).append(t)
    linhas = []
    for pf in programacoes:
        trfs = por_pf.get(pf['id_programacao'], [])
        avisos = []
        reg = {
            'Title': str(pf['id_programacao']),
            'IdPlanoAcao': pf['id_plano_acao'],
            'NumeroPF': pf.get('tx_numero_programacao'),
            'Situacao': pf.get('tx_situacao_programacao'),
            'DataRecebimento': _data(pf.get('dh_recebimento_programacao'), 'DataRecebimento', avisos),
            'UGEmitente': pf.get('ug_emitente_programacao'),
            'UGFavorecida': pf.get('ug_favorecida_programacao'),
            'Valor': round(sum(t.get('vl_valor_trf') or 0 for t in trfs), 2) if trfs else None,
            'FontesRecurso': _distintos(t.get('cd_fonte_recurso_trf') for t in trfs),
            'CategoriaGasto': _distintos(t.get('cd_categoria_gasto_trf') for t in trfs),
            'SituacaoContabil': _distintos(t.get('cd_situacao_contabil_trf') for t in trfs),
        }
        reg['AvisoDados'] = '; '.join(avisos) or None
        linhas.append(_com_hash(reg))
    return linhas


VAZIO_FIN = {'ValorPFRecebido': None, 'QtdPF': 0, 'FontesRecurso': None, 'DataUltimaPF': None}
VAZIO_NC = {'QtdNC': 0, 'DataUltimaNC': None}


def _resumo_nc(notas):
    """Quantidade e data da última NC ENVIADA por plano, no mesmo critério do PF. Sem valor (ADR 0009, item C)."""
    resumo = {}
    for nota in notas:
        if nota.get('tx_situacao_nota') == 'ENVIADA':
            d = resumo.setdefault(nota['id_plano_acao'], {'QtdNC': 0, 'DataUltimaNC': None})
            d['QtdNC'] += 1
            data = (nota.get('dt_emissao_nota') or '')[:10]
            if data and data > (d['DataUltimaNC'] or ''):
                d['DataUltimaNC'] = data
    return resumo


def _financeiro(programacoes, repasses):
    """
    PF recebido por plano, segundo o TransfereGov: soma dos repasses (trf) das
    programações financeiras ENVIADAS e as fontes de recurso usadas. É valor de
    referência; em 2026-10-20 bateu com a planilha da COPES em 3 de 5 TEDs.
    """
    enviadas = {pf['id_programacao']: pf for pf in programacoes
                if pf.get('tx_situacao_programacao') == 'ENVIADA'}
    por_plano = {}
    for pf in enviadas.values():
        d = por_plano.setdefault(pf['id_plano_acao'], {'valor': 0.0, 'qtd': 0, 'fontes': set(), 'ultima': ''})
        d['qtd'] += 1
        d['ultima'] = max(d['ultima'], (pf.get('dh_recebimento_programacao') or '')[:10])
    for t in repasses:
        pf = enviadas.get(t['id_programacao'])
        if pf:
            d = por_plano[pf['id_plano_acao']]
            d['valor'] += t.get('vl_valor_trf') or 0
            if t.get('cd_fonte_recurso_trf'):
                d['fontes'].add(t['cd_fonte_recurso_trf'])
    return {plano: {'ValorPFRecebido': round(d['valor'], 2), 'QtdPF': d['qtd'],
                    'FontesRecurso': ', '.join(sorted(d['fontes'])) or None,
                    'DataUltimaPF': d['ultima'] or None}
            for plano, d in por_plano.items()}


if __name__ == '__main__':
    main()
