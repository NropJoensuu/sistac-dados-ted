"""
Coleta os convênios do CNPq nos arquivos abertos do Transferegov (SICONV) e
grava dados/convenios.json.

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

URL_BASE = 'https://api-publica.transferegov.gestao.gov.br/downloads/dadosgov/'
COD_INST = '20501'  # prefixo dos programas do CNPq no SICONV
ARQUIVOS = ['siconv_programa', 'siconv_programa_proposta', 'siconv_proposta',
            'siconv_convenio', 'data_carga_siconv']
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
            'QtdTA': int(c['QTD_TA']) if c['QTD_TA'] else None,
            'QtdProrroga': int(c['QTD_PRORROGA']) if c['QTD_PRORROGA'] else None,
        }
        reg['AvisoDados'] = '; '.join(avisos) or None
        reg['HashAPI'] = hashlib.sha1(json.dumps(reg, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        registros[c['NR_CONVENIO']] = reg

    if not registros:
        # fonte fora do ar ou formato mudou: não sobrescreve o arquivo do dia anterior
        sys.exit('Nenhum convênio do CNPq encontrado; arquivo mantido.')

    data_carga = next(linhas(pasta, 'data_carga_siconv'))['data_carga']
    os.makedirs(PASTA, exist_ok=True)
    dados = sorted(registros.values(), key=lambda r: r['Title'].zfill(12))  # há números com letras
    with open(os.path.join(PASTA, 'convenios.json'), 'w', encoding='utf-8') as f:
        json.dump(dados, f, ensure_ascii=False, indent=1)
        f.write('\n')
    with open(os.path.join(PASTA, 'convenios_data_carga.txt'), 'w', encoding='utf-8') as f:
        f.write(data_carga + '\n')
    print('programas CNPq:', len(programas), '| propostas:', len(propostas),
          '| convênios:', len(dados), '| data da carga na fonte:', data_carga)


if __name__ == '__main__':
    main()
