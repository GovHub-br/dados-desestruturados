from __future__ import annotations


def candidate_scope_instruction(scope: str) -> str:
    """Explica em texto corrido a responsabilidade da LLM em cada escopo."""
    if scope == "criacao_inicial_layout":
        return (
            "Esta e uma criacao inicial de layout signature: nao existe layout ativo "
            "que possa ser reaproveitado. A DAG ja definiu a identidade do documento, "
            "a referencia do contrato e as regras operacionais. Sua responsabilidade e "
            "criar somente os mapeamentos canonicos que ensinam a DAG 2 a localizar os "
            "valores brutos nos artefatos recebidos. Nao crie metadados de identidade "
            "do documento, versao, publicacao ou regras de execucao; esses campos pertencem "
            "ao esqueleto deterministico da DAG."
        )
    if scope == "correcao_parcial_mapeamento":
        return (
            "Esta e uma correcao parcial de layout signature. O layout existente continua "
            "sendo a referencia e apenas os mapeamentos afetados pela falha podem mudar. "
            "Preserve todos os demais mapeamentos e use as evidencias recebidas para corrigir "
            "somente os paths permitidos. Metadados operacionais, publicacao e contrato nao "
            "fazem parte da sua resposta."
        )
    return (
        "Esta e uma regeneracao completa de mapeamentos porque o layout anterior deixou "
        "de ser confiavel. Reconstrua somente os mapeamentos permitidos pelo contrato a "
        "partir das evidencias atuais. A DAG continua responsavel por contrato, identidade "
        "do documento, governanca, versao e publicacao."
    )


def candidate_contract_instruction() -> str:
    """Explica como interpretar contrato, paths e arrays antes do bloco JSON."""
    return (
        "O proximo bloco contem a semantica do contrato, a estrutura permitida do schema "
        "de saida e os alvos que voce deve mapear. requisitos_mapeamento.campos_obrigatorios "
        "lista os campos que devem receber uma origem deterministica. Quando um campo trouxer "
        "observacoes_obrigatorias, crie uma entrada para cada conjunto de seletores e tambem "
        "mapeie todos os campos_contexto_obrigatorios na mesma observacao. paths_permitidos sao "
        "as unicas chaves aceitas no mapeamento_canonico. "
        "Cada trecho listado em arrays_que_exigem_seletor exige filtro explicito entre "
        "colchetes na chave final: se o path permitido for colecao.itens.valor e "
        "colecao.itens for um array, use colecao.itens[chave=valor_observado].valor; "
        "nunca use colecao.itens.valor sem esse seletor. Use um filtro que identifique "
        "uma unica observacao. Quando o "
        "contrato definir papeis semanticos para observacoes comparaveis, use exatamente "
        "esses papeis para distingui-las. paths_permitidos ja exclui valores fixos "
        "do contrato: nao os inclua no mapeamento_canonico, pois a DAG 2 os preenche "
        "deterministicamente. Nao invente campos, contratos ou valores."
    )


def candidate_structure_instruction() -> str:
    """Explica o papel do exemplo de layout antes de envia-lo ao modelo."""
    return (
        "O proximo objeto e um exemplo da estrutura que a resposta precisa respeitar. Ele "
        "mostra um modelo completo no nivel raiz, as secoes esperadas, os tipos de origem aceitos e a "
        "sintaxe de seletores de tabela e de arrays. Trate-o como modelo de forma, nunca "
        "como evidencia do documento: nomes de arquivos, rotulos, indices e valores usados "
        "no seu candidato devem vir exclusivamente dos artefatos recebidos depois deste "
        "exemplo. Sua resposta final deve ser o conteudo de modelo_resposta_no_nivel_raiz, "
        "sem envolver os campos em cabecalho_obrigatorio, modelo_resposta_no_nivel_raiz ou "
        "qualquer outro objeto adicional. Cada entrada de mapeamento_canonico deve ser uma "
        "instrucao executavel com "
        "tipo_origem permitido, e nao uma descricao em texto. Uma celula de tabela mapeada "
        "para uma observacao representa o registro indicado pelo seletor; quando o path "
        "terminar em um campo terminal, a DAG grava somente o valor extraido nesse campo. "
        "Para celula_de_tabela e cabecalho_de_tabela, informe os indices observados; para "
        "linhas_de_tabela, informe as faixas e colunas a capturar. Nao use regex nem "
        "padrao_cabecalho_aceito em tabelas: a DAG le diretamente a posicao informada e "
        "preserva o cabecalho bruto. Regex e reservado a bloco_textual."
    )


def candidate_artifacts_instruction() -> str:
    """Explica como usar exclusivamente as evidencias carregadas pela DAG."""
    return (
        "Os proximos artefatos formam o conjunto de evidencias recuperado pela etapa anterior. "
        "Nele estao as fontes necessarias para localizar os dados brutos pedidos pelo contrato, "
        "mas nem todo arquivo precisa ser usado no candidato. Para cada alvo mapeavel, escolha "
        "somente a fonte cuja secao, entidade, medida e periodo correspondam exatamente ao que "
        "o contrato pede. Se houver fontes com granularidades diferentes, nao use uma fonte "
        "agregada para preencher uma observacao mais detalhada. Todo arquivo_origem citado no "
        "candidato deve aparecer neste bloco. Observe secoes, rotulos de linha e cabecalhos reais "
        "antes de definir os seletores. Quando a fonte escolhida possuir mais de uma coluna de "
        "de observacao exigida pelo contrato, crie um mapeamento para cada papel correspondente, "
        "e nao apenas para a primeira coluna. Para celulas e cabecalhos de tabela, use os "
        "indices observados; para faixas de linhas, use linhas_de_tabela. Nao use regex para "
        "validar cabecalhos de tabela."
    )


def candidate_final_instruction() -> str:
    """Recapitula a tarefa imediatamente antes da resposta JSON."""
    return (
        "Agora produza somente um objeto JSON valido de layout_signature_candidato. No nivel "
        "raiz inclua obrigatoriamente tipo_artefato, status_layout, escopo_correcao, "
        "document_id, execution_id_origem, base_layout_signature, fontes_relevantes, "
        "regras_deteccao_mudanca, mapeamento_canonico e metadados_estruturais_evidencia. "
        "Nao aninhe esses campos em cabecalho_obrigatorio ou outro envelope. Mapeie apenas paths "
        "permitidos e use somente artefatos carregados. Nao resolva valores finais, nao "
        "inclua explicacoes, markdown, publicacao, versao, contrato ou regras de execucao."
    )


def candidate_layout_repair_system_prompt() -> str:
    """Prompt usado para corrigir um candidato rejeitado pelos validadores."""
    return (
        "Voce deve corrigir um layout_signature_candidato que foi rejeitado por "
        "validacao estrutural ou de dominio. Leia correcao_candidato.erro_validacao "
        "e correcao_candidato.candidato_invalido no payload. Corrija somente o necessario para eliminar "
        "esse erro, preservando todas as partes validas e o escopo permitido. "
        "Devolva novamente o objeto JSON completo do layout candidato, sem markdown "
        "ou explicacoes. fontes_relevantes, regras_deteccao_mudanca, "
        "mapeamento_canonico e metadados_estruturais_evidencia sao secoes irmas no "
        "nivel raiz; nunca trate o nome de uma dessas secoes como campo de "
        "mapeamento_canonico. As chaves de mapeamento_canonico devem apontar somente "
        "para paths existentes em estrutura_schema_saida.paths_permitidos e cada valor deve ser "
        "uma instrucao de resolucao no formato exemplo_estrutura_layout_signature; nunca uma "
        "string ou objeto somente com instrucao. Os campos obrigatorios do cabecalho pertencem "
        "ao nivel raiz da resposta; cabecalho_obrigatorio e apenas uma descricao antiga, nunca "
        "um objeto a ser emitido. Para cada trecho listado em arrays_que_exigem_seletor, a chave "
        "do mapeamento deve conter um filtro entre colchetes que identifique uma observacao; "
        "nao atravesse arrays com paths sem filtro. Use formatos_de_origem do exemplo. Nao altere document_id, execution_id_origem, "
        "escopo_correcao, contrato semantico, regras de governanca ou layouts "
        "publicados. Nao mapeie valores fixos do contrato: eles nao aparecem em "
        "paths_permitidos e sao preenchidos deterministicamente pela DAG 2. Nao gere valores finais de negocio. Para tabelas, remova qualquer regex "
        "ou padrao_cabecalho_aceito e informe os indices observados de linha e coluna."
    )


def artifact_selection_system_prompt() -> str:
    """Prompt da primeira chamada LLM para escolher arquivos pelo inventario."""
    return (
        "Voce atua na primeira etapa do fallback de layout signature. "
        "Sua tarefa agora NAO e gerar layout, NAO e resolver valores finais e "
        "NAO e criar mapeamento_canonico. "
        "Voce deve ler o contrato semantico, o contexto da falha e o resumo do "
        "inventory.json e escolher quais artefatos da extracao precisam ser "
        "abertos pela DAG 3 na proxima chamada. "
        "Use somente caminhos que existam em inventario_extracao.resumo.items[].path. "
        "Escolha o menor conjunto suficiente de arquivos para permitir a geracao "
        "do layout_signature_candidato. "
        "Para correcao parcial, priorize artefatos ligados aos campos quebrados "
        "ou as regras reprovadas. "
        "Para regeneracao total ou criacao inicial, escolha os artefatos que melhor "
        "cobrem os campos do schema_saida do contrato, ainda evitando abrir o "
        "documento inteiro quando o inventario apontar tabelas, graficos ou secoes "
        "mais especificas. "
        "Informe em coberturas somente o atributo path de cada item listado em "
        "contrato_semantico_relevante.contrato_semantico.requisitos_mapeamento.campos_obrigatorios. Esses sao os "
        "unicos campos que exigem evidencia nesta etapa. "
        "Nao declare campos estruturais, metadados, constantes, campos derivados ou "
        "qualquer outro path fora dessa lista, pois a DAG os preenche ou valida "
        "deterministicamente. Cada artefato "
        "comprova, com ancoras literais existentes no proprio arquivo, por exemplo "
        "um titulo de secao, rotulo de linha e cabecalho de tabela. Nao enumere "
        "campos fora dessa lista. Nao declare cobertura sem ancoras "
        "verificaveis. Em criacao inicial ou regeneracao, cubra todos os campos "
        "minimos de valor do contrato. "
        "Se um arquivo JSONL grande for necessario, selecione o caminho dele; a DAG "
        "vai aplicar chunking quando carregar o conteudo. "
        "Responda somente com JSON estrito, sem markdown e sem explicacao externa. "
        "O formato obrigatorio e: "
        "{"
        "\"tipo_artefato\":\"selecao_artefatos_layout\","
        "\"artifact_paths\":["
        "{"
        "\"path\":\"tables/table001.json\","
        "\"motivo\":\"por que este artefato precisa ser aberto\","
        "\"coberturas\":[{\"campo_saida\":\"campo.ou.path.do.schema\","
        "\"ancoras\":[\"rotulo literalmente observado\",\"cabecalho observado\"]}]"
        "}"
        "]"
        "}. "
        "Nao inclua caminhos inventados, URLs MinIO, object keys completos nem "
        "arquivos que nao estejam listados no inventario."
    )


def artifact_selection_repair_system_prompt() -> str:
    """Prompt de retry quando a selecao nao passa nas validacoes deterministicas."""
    return (
        "A sua selecao de artefatos anterior foi rejeitada pela validacao deterministica. "
        "Leia correcao_selecao_artefatos.erro_validacao e, quando presente, a resposta "
        "anterior. Corrija os paths ou as ancoras exatamente como o erro indica. Uma ancora "
        "so pode ser declarada se seu texto literal estiver no arquivo selecionado; escolha "
        "outro artefato do inventario somente quando o campo estiver em "
        "contrato_semantico_relevante.contrato_semantico.requisitos_mapeamento.campos_obrigatorios e a nova fonte o "
        "comprovar. Se a cobertura anterior for de campo estrutural ou fora dessa lista, "
        "remova-a; nao procure outra evidencia para ela. Preserve as partes validas da "
        "selecao, cubra todos os campos minimos exigidos e responda somente com este JSON "
        "completo, sem markdown ou explicacoes: "
        "{\"tipo_artefato\":\"selecao_artefatos_layout\",\"artifact_paths\":[...]}."
    )
