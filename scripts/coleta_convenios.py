"""
Coleta os convênios do CNPq nos arquivos abertos do Transferegov (SICONV) e
grava dados/convenios.json e, desde a ADR 0009 (passo b), os desembolsos (com a OB),
os empenhos e o cronograma de desembolso desses convênios.

Mesma lógica de cargaSICONV() do sistac (project/core/services.py):
programas cujo COD_PROGRAMA começa com 20501 (CNPq) -> programa_proposta ->
proposta -> convênio. Fonte: área de download que substituiu o
repositorio.dados.gov.br em 31/08/2026 (Comunicado Transferegov nº 23/2026).
Só dados públicos; dados bancários e endereço do proponente não entram.

Uso: python3 scripts/coleta_convenios.py [pasta_com_zips]
Sem argumento, baixa os .zip numa pasta temporária.
"""

import csv
import hashlib
import io
import json
import os
import sys
import tempfile
import time
import urllib.request
import zipfile
from calendar import monthrange

URL_BASE = 'https://api-publica.transferegov.gestao.gov.br/downloads/dadosgov/'
COD_INST = '20501'  # prefixo dos programas do CNPq no SICONV
ARQUIVOS = ['siconv_programa', 'siconv_programa_proposta', 'siconv_proposta',
            'siconv_convenio', 'siconv_desembolso', 'siconv_empenho',
            'siconv_empenho_desembolso', 'siconv_cronograma_desembolso',
            'data_carga_siconv']
PASTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'dados')


def baixa(pasta):
    for nome in ARQUIVOS:
        destino = os.path.join(pasta, nome + '.zip')
        for tentativa in range(3):
            try:
                req = urllib.request.Request(URL_BASE + nome + '.zip',
                                             headers={'User-Agent': 'sistac-dados-ted'})
                with urllib.request.urlopen(req, timeout=600) as resp, open(destino, 'wb') as f:
                    while bloco := resp.read(1 << 20):
                        f.write(bloco)
                break
            except OSError:
                if tentativa == 2:
                    raise
                time.sleep(60)


def linhas(pasta, nome):
    """Lê o .csv de dentro do .zip sem descompactar em disco."""
    with zipfile.ZipFile(os.path.join(pasta, nome + '.zip')) as z:
        with z.open(z.namelist()[0]) as bruto:
            leitor = csv.DictReader(io.TextIOWrapper(bruto, encoding='utf-8-sig', newline=''),
                                    delimiter=';')
            yield from leitor


def data_iso(valor, campo, avisos):
    """dd/mm/aaaa -> aaaa-mm-dd; ano fora de 1900-2100 vira vazio e vai para AvisoDados."""
    if not valor:
        return None
    d, m, a = valor[:10].split('/')
    if not ('1900' <= a <= '2100'):
        avisos.append(f'{campo} inválida na fonte: {valor}')
        return None
    return f'{a}-{m}-{d}'


def numero(valor):
    return float(valor.replace(',', '.')) if valor else None


def com_hash(reg, avisos):
    reg['AvisoDados'] = '; '.join(avisos) or None
    reg['HashAPI'] = hashlib.sha1(json.dumps(reg, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return reg


def grava(nome, dados):
    with open(os.path.join(PASTA, nome), 'w', encoding='utf-8') as f:
        json.dump(dados, f, ensure_ascii=False, indent=1)
        f.write('\n')


def financeiro(pasta, registros):
    """Desembolsos (com a OB), empenhos e cronograma dos convênios do CNPq (ADR 0009, passo b)."""
    desembolsos = {}
    for d in linhas(pasta, 'siconv_desembolso'):
        if d['NR_CONVENIO'] in registros and d['ID_DESEMBOLSO'] not in desembolsos:
            desembolsos[d['ID_DESEMBOLSO']] = d

    empenhos, repetidos = {}, set()
    for e in linhas(pasta, 'siconv_empenho'):
        if e['NR_CONVENIO'] not in registros:
            continue
        if e['ID_EMPENHO'] in empenhos:  # o SICONV traz IDs repetidos (models.py, classe Empenho)
            repetidos.add(e['ID_EMPENHO'])
            continue
        empenhos[e['ID_EMPENHO']] = e

    ne_do_desembolso = {}
    for v in linhas(pasta, 'siconv_empenho_desembolso'):
        if v['ID_DESEMBOLSO'] in desembolsos and v['ID_EMPENHO'] in empenhos:
            ne_do_desembolso.setdefault(v['ID_DESEMBOLSO'], set()).add(empenhos[v['ID_EMPENHO']]['NR_EMPENHO'])

    lista_desemb = []
    for id_d, d in desembolsos.items():
        avisos = []
        lista_desemb.append(com_hash({
            'Title': id_d,
            'NumeroConvenio': d['NR_CONVENIO'],
            'DataDesembolso': data_iso(d['DATA_DESEMBOLSO'], 'DataDesembolso', avisos),
            'NumeroOB': d['NR_SIAFI'] or None,
            'UGEmitente': d['UG_EMITENTE_DH'] or None,
            'Observacao': d['OBSERVACAO_DH'] or None,
            'Valor': numero(d['VL_DESEMBOLSADO']),
            'NumerosEmpenho': ', '.join(sorted(ne_do_desembolso.get(id_d, ()))) or None,
        }, avisos))

    lista_emp = []
    for id_e, e in empenhos.items():
        avisos = ['ID_EMPENHO repetido na fonte; mantida a primeira linha'] if id_e in repetidos else []
        reg = com_hash({
            'Title': id_e,
            'NumeroConvenio': e['NR_CONVENIO'],
            'NumeroEmpenho': e['NR_EMPENHO'] or None,
            'TipoNota': e['DESC_TIPO_NOTA'] or None,
            'DataEmissao': data_iso(e['DATA_EMISSAO'], 'DataEmissao', avisos),
            'Situacao': e['DESC_SITUACAO_EMPENHO'] or None,
            'NaturezaDespesa': e['NATUREZA_DESPESA'] or None,
            'FonteRecurso': e['FONTE_RECURSO'] or None,
            'PlanoInterno': e['PLANO_INTERNO'] or None,
            'PTRES': e['PTRES'] or None,
            'Valor': numero(e['VALOR_EMPENHO']),
            'Observacao': e['OBSERVACAO_EMPENHO'] or None,
        }, avisos)
        # A observação é texto livre e traz nomes de pessoas: não entra no JSON público
        # (ADR 0009, critério 2). Sai depois do hash para o HashAPI não mudar e o fluxo
        # não regravar os 2.572 empenhos; o SHA-1 não expõe o texto.
        del reg['Observacao']
        lista_emp.append(reg)

    # desembolsos agrupados por data e OB, em ordem de data, como em detalhes_convenio()
    agrupado = {}
    for r in lista_desemb:
        chave = (r['NumeroConvenio'], r['DataDesembolso'] or '', r['NumeroOB'] or '')
        agrupado[chave] = agrupado.get(chave, 0) + (r['Valor'] or 0)
    desemb_conv = {}
    for (conv, data, _ob), valor in sorted(agrupado.items()):
        desemb_conv.setdefault(conv, []).append((data, valor))

    parcelas = {}
    for c in linhas(pasta, 'siconv_cronograma_desembolso'):
        if c['NR_CONVENIO'] in registros:
            parcelas.setdefault(c['NR_CONVENIO'], []).append(c)

    lista_crono, chaves = [], set()
    for conv, ps in parcelas.items():
        desembolsado = registros[conv]['ValorDesembolsado'] or 0
        # Concedente primeiro; dentro do tipo, ordem cronológica numérica (o legado ordenava
        # ano e mês como texto, o que punha outubro antes de fevereiro)
        ps.sort(key=lambda p: (p['TIPO_RESP_CRONO_DESEMBOLSO'], int(p['ANO_CRONO_DESEMBOLSO']),
                               int(p['MES_CRONO_DESEMBOLSO']), int(p['NR_PARCELA_CRONO_DESEMBOLSO'] or 0)))
        acumulado = 0
        for p in ps:
            avisos = []
            ano, mes = int(p['ANO_CRONO_DESEMBOLSO']), int(p['MES_CRONO_DESEMBOLSO'])
            valor = numero(p['VALOR_PARCELA_CRONO_DESEMBOLSO']) or 0
            situacao = data_quit = None
            if p['TIPO_RESP_CRONO_DESEMBOLSO'] == 'Concedente':
                acumulado += valor
                situacao = 'Quitada' if acumulado <= desembolsado + 0.005 else 'Em aberto'
                if situacao == 'Quitada':
                    soma = 0
                    for data, v in desemb_conv.get(conv, []):
                        soma += v
                        if acumulado <= soma + 0.005:
                            data_quit = data or None
                            break
            chave = f"{conv}-{p['TIPO_RESP_CRONO_DESEMBOLSO']}-{p['NR_PARCELA_CRONO_DESEMBOLSO']}"
            if chave in chaves:
                avisos.append('parcela repetida na fonte')
                n = 2
                while f'{chave}-{n}' in chaves:
                    n += 1
                chave = f'{chave}-{n}'
            chaves.add(chave)
            lista_crono.append(com_hash({
                'Title': chave,
                'NumeroConvenio': conv,
                'Parcela': int(p['NR_PARCELA_CRONO_DESEMBOLSO']) if p['NR_PARCELA_CRONO_DESEMBOLSO'] else None,
                'Responsavel': p['TIPO_RESP_CRONO_DESEMBOLSO'] or None,
                'DataPrevista': f'{ano:04d}-{mes:02d}-{monthrange(ano, mes)[1]:02d}',
                'Valor': valor,
                'Situacao': situacao,
                'DataQuitacao': data_quit,
            }, avisos))

    ultimo = {}
    for r in lista_desemb:
        if r['DataDesembolso']:
            ultimo[r['NumeroConvenio']] = max(ultimo.get(r['NumeroConvenio'], ''), r['DataDesembolso'])
    return lista_desemb, lista_emp, lista_crono, ultimo


def main():
    pasta = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix='siconv_')
    if len(sys.argv) == 1:
        baixa(pasta)

    programas = {}
    for p in linhas(pasta, 'siconv_programa'):
        if p['COD_PROGRAMA'].startswith(COD_INST):
            programas.setdefault(p['ID_PROGRAMA'], p)

    # proposta -> primeiro programa do CNPq (como no legado)
    prog_da_proposta = {}
    for pp in linhas(pasta, 'siconv_programa_proposta'):
        if pp['ID_PROGRAMA'] in programas:
            prog_da_proposta.setdefault(pp['ID_PROPOSTA'], pp['ID_PROGRAMA'])

    propostas = {}
    for pr in linhas(pasta, 'siconv_proposta'):
        if pr['ID_PROPOSTA'] in prog_da_proposta:
            propostas[pr['ID_PROPOSTA']] = pr

    registros = {}
    for c in linhas(pasta, 'siconv_convenio'):
        if c['ID_PROPOSTA'] not in prog_da_proposta or c['NR_CONVENIO'] in registros:
            continue
        prog = programas[prog_da_proposta[c['ID_PROPOSTA']]]
        prop = propostas.get(c['ID_PROPOSTA'], {})
        avisos = []
        reg = {
            'Title': c['NR_CONVENIO'],
            'IdProposta': int(c['ID_PROPOSTA']),
            'NrProposta': prop.get('NR_PROPOSTA') or None,
            'CodProgramaSiconv': prog['COD_PROGRAMA'],
            'NomeProgramaSiconv': prog['NOME_PROGRAMA'],
            'AnoPrograma': int(prog['ANO_DISPONIBILIZACAO']) if prog['ANO_DISPONIBILIZACAO'] else None,
            'UF': prop.get('UF_PROPONENTE') or None,
            'Municipio': prop.get('MUNIC_PROPONENTE') or None,
            'Proponente': prop.get('NM_PROPONENTE') or None,
            'CNPJProponente': prop.get('IDENTIF_PROPONENTE') or None,
            'Objeto': prop.get('OBJETO_PROPOSTA') or None,
            'Situacao': c['SIT_CONVENIO'] or None,
            'Subsituacao': c['SUBSITUACAO_CONV'] or None,
            'InstrumentoAtivo': c['INSTRUMENTO_ATIVO'] == 'SIM',
            'NrProcesso': c['NR_PROCESSO'] or None,
            'DataAssinatura': data_iso(c['DIA_ASSIN_CONV'], 'DataAssinatura', avisos),
            'DataPublicacao': data_iso(c['DIA_PUBL_CONV'], 'DataPublicacao', avisos),
            'VigenciaInicio': data_iso(c['DIA_INIC_VIGENC_CONV'], 'VigenciaInicio', avisos),
            'VigenciaFim': data_iso(c['DIA_FIM_VIGENC_CONV'], 'VigenciaFim', avisos),
            'ValorGlobal': numero(c['VL_GLOBAL_CONV']),
            'ValorRepasse': numero(c['VL_REPASSE_CONV']),
            'ValorContrapartida': numero(c['VL_CONTRAPARTIDA_CONV']),
            'ValorEmpenhado': numero(c['VL_EMPENHADO_CONV']),
            'ValorDesembolsado': numero(c['VL_DESEMBOLSADO_CONV']),
            'ValorIngressoContrapartida': numero(c['VL_INGRESSO_CONTRAPARTIDA']),
            'ValorRendimentoAplicacao': numero(c['VL_RENDIMENTO_APLICACAO']),
            'ValorSaldoRemanTesouro': numero(c['VL_SALDO_REMAN_TESOURO']),
            'ValorSaldoRemanConvenente': numero(c['VL_SALDO_REMAN_CONVENENTE']),
            'ValorSaldoConta': numero(c['VL_SALDO_CONTA']),
            'OperaOBTV': c['IND_OPERA_OBTV'] == 'SIM',
            'QtdTA': int(c['QTD_TA']) if c['QTD_TA'] else None,
            'QtdProrroga': int(c['QTD_PRORROGA']) if c['QTD_PRORROGA'] else None,
        }
        reg['_avisos'] = avisos
        registros[c['NR_CONVENIO']] = reg

    if not registros:
        # fonte fora do ar ou formato mudou: não sobrescreve o arquivo do dia anterior
        sys.exit('Nenhum convênio do CNPq encontrado; arquivo mantido.')

    desemb, emp, crono, ultimo = financeiro(pasta, registros)
    for nr, reg in registros.items():
        reg['DataUltimoDesembolso'] = ultimo.get(nr)
        com_hash(reg, reg.pop('_avisos'))

    data_carga = next(linhas(pasta, 'data_carga_siconv'))['data_carga']
    os.makedirs(PASTA, exist_ok=True)
    por_titulo = lambda r: r['Title'].zfill(20)  # há números de convênio com letras
    dados = sorted(registros.values(), key=por_titulo)
    grava('convenios.json', dados)
    grava('convenio_desembolsos.json', sorted(desemb, key=por_titulo))
    grava('convenio_empenhos.json', sorted(emp, key=por_titulo))
    grava('convenio_cronograma.json', sorted(crono, key=lambda r: r['Title']))
    with open(os.path.join(PASTA, 'convenios_data_carga.txt'), 'w', encoding='utf-8') as f:
        f.write(data_carga + '\n')
    print('programas CNPq:', len(programas), '| propostas:', len(propostas),
          '| convênios:', len(dados), '| desembolsos:', len(desemb), '| empenhos:', len(emp),
          '| parcelas:', len(crono), '| data da carga na fonte:', data_carga)


if __name__ == '__main__':
    main()
