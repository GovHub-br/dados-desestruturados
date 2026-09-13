from __future__ import annotations

# Cada escopo e um texto completo e independente, nao uma variacao de frase. Ficam
# em um mapa para que cada um vire um prompt versionado separado no Langfuse: mudar
# a instrucao de criacao inicial nao deve mexer no historico da correcao parcial.
CANDIDATE_SCOPE_PROMPTS: dict[str, str] = {
    "criacao_inicial_layout": (
        "Esta e uma criacao inicial de layout signature: nao existe layout ativo "
        "que possa ser reaproveitado. A DAG ja definiu a identidade do documento, "
        "a referencia do contrato e as regras operacionais. Sua responsabilidade e "
        "criar somente os mapeamentos canonicos que ensinam a DAG 2 a localizar os "
        "valores brutos nos artefatos recebidos. Nao crie metadados de identidade "
        "do documento, versao, publicacao ou regras de execucao; esses campos pertencem "
        "ao esqueleto deterministico da DAG."
    ),
    "correcao_parcial_mapeamento": (
        "Esta e uma correcao parcial de layout signature. O layout existente continua "
        "sendo a referencia e apenas os mapeamentos afetados pela falha podem mudar. "
        "Preserve todos os demais mapeamentos e use as evidencias recebidas para corrigir "
        "somente os paths permitidos. Metadados operacionais, publicacao e contrato nao "
        "fazem parte da sua resposta."
    ),
    "regeneracao_total_mapeamento": (
        "Esta e uma regeneracao completa de mapeamentos porque o layout anterior deixou "
        "de ser confiavel. Reconstrua somente os mapeamentos permitidos pelo contrato a "
        "partir das evidencias atuais. A DAG continua responsavel por contrato, identidade "
        "do documento, governanca, versao e publicacao."
    ),
}

# Escopo desconhecido sempre caiu na regeneracao total; preservado explicitamente.
CANDIDATE_SCOPE_PADRAO = "regeneracao_total_mapeamento"


def candidate_scope_instruction(scope: str) -> str:
    """Explica em texto corrido a responsabilidade da LLM em cada escopo."""
    return CANDIDATE_SCOPE_PROMPTS.get(scope, CANDIDATE_SCOPE_PROMPTS[CANDIDATE_SCOPE_PADRAO])


def candidate_contract_instruction() -> str:
    """Explica como interpretar contrato, paths e arrays antes do bloco JSON."""
    return (
        "O proximo bloco contem a semantica do contrato, a estrutura permitida do schema "
        "de saida e os alvos que voce deve mapear. requisitos_mapeamento.campos_obrigatorios "
        "lista os campos que devem receber uma origem deterministica. Quando um campo trouxer "
        "observacoes_obrigatorias, crie uma entrada para cada conjunto de seletores e tambem "
        "mapeie todos os campos_contexto_obrigatorios na mesma observacao. paths_permitidos sao "
        "as unicas chaves aceitas no mapeamento_canonico. "
        "Um array admite somente dois modos. Para mapear um item individual, use filtro "
        "explicito entre colchetes que identifique uma unica observacao, por exemplo "
        "colecao.itens[chave=valor_observado].valor. Nunca use indices posicionais "
        "como [0] ou [1]: eles nao identificam semanticamente uma observacao e sao "
        "invalidos. Para preencher a colecao inteira "
        "por linhas_de_tabela, use exatamente o path raiz da colecao, sem filtro, por "
        "exemplo colecao.itens. Nunca misture os dois modos. "
        "Uma observacao com obrigatorio=false deve ser mapeada quando houver evidencia, mas sua ausencia "
        "nao invalida o candidato. Quando o contrato definir papeis semanticos para observacoes comparaveis, use exatamente "
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
        "validar cabecalhos de tabela. Se uma evidencia obrigatoria nao estiver presente, "
        "nao deduza, nao troque a medida nem use periodo aproximado. Declare a ausencia em "
        "campos_nao_mapeados com o path, os seletores exigidos, o motivo e os artefatos "
        "verificados. Essa declaracao encerra a busca para aquele requisito."
    )


def candidate_final_instruction() -> str:
    """Recapitula a tarefa imediatamente antes da resposta JSON."""
    return (
        "Agora produza somente um objeto JSON valido de layout_signature_candidato. No nivel "
        "raiz inclua obrigatoriamente tipo_artefato, status_layout, escopo_correcao, "
        "document_id, execution_id_origem, base_layout_signature, fontes_relevantes, "
        "regras_deteccao_mudanca, campos_nao_mapeados, mapeamento_canonico e "
        "metadados_estruturais_evidencia. campos_nao_mapeados e uma lista: cada item usa "
        "path, seletores, motivo e artefatos_verificados. Use-a somente quando um requisito "
        "obrigatorio nao puder ser comprovado pelos artefatos recebidos; nesse caso, nao crie "
        "um mapeamento alternativo para o mesmo requisito. "
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
        "do mapeamento deve conter um filtro entre colchetes no formato campo[chave=valor], "
        "nunca um indice como [0] ou [1]; nao atravesse arrays com paths sem filtro, inclusive "
        "arrays aninhados, e nunca concatene condicoes com '&' dentro de um filtro. "
        "Use formatos_de_origem do exemplo. Nao altere document_id, execution_id_origem, "
        "escopo_correcao, contrato semantico, regras de governanca ou layouts "
        "publicados. Nao mapeie valores fixos do contrato: eles nao aparecem em "
        "paths_permitidos e sao preenchidos deterministicamente pela DAG 2. Nao gere valores finais de negocio. Para tabelas, remova qualquer regex "
        "ou padrao_cabecalho_aceito e informe os indices observados de linha e coluna. Se a "
        "evidencia de um requisito obrigatorio nao existir, nao tente corrigi-lo por inferencia: "
        "registre-o em campos_nao_mapeados usando path, seletores, motivo e "
        "artefatos_verificados."
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
        "O inventario desta etapa contem somente tabelas e graficos: selecione apenas "
        "esses artefatos. Nao procure texto corrido, blocos, secoes, metricas ou outros "
        "tipos de extracao nesta chamada. "
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
        "Quando um campo obrigatorio trouxer descricao ou orientacao_origem, trate esses "
        "dados como criterio semantico de selecao: priorize fontes_preferenciais e evidencias_esperadas, "
        "evite fontes_a_evitar e respeite a granularidade_esperada. Essas orientacoes pertencem ao "
        "contrato e podem ser diferentes para qualquer dominio; nao substitua seu conteudo por suposicoes. "
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
        "O schema de resposta e contratual: use os nomes de chave exatamente como "
        "definidos abaixo; nao use sinonimos. Em especial, cada item de coberturas "
        "DEVE conter campo_saida e ancoras. A chave campo nao e aceita e uma "
        "cobertura sem ancoras e invalida. "
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
        "anterior. Quando artefatos_carregados_para_correcao estiver presente, ele contem "
        "a evidencia real dos arquivos escolhidos na tentativa anterior: copie as ancoras "
        "literalmente dessa evidencia ou remova/troque a cobertura que ela nao comprova. "
        "Corrija os paths ou as ancoras exatamente como o erro indica. Uma ancora "
        "so pode ser declarada se seu texto literal estiver no arquivo selecionado; escolha "
        "outro artefato do inventario somente quando o campo estiver em "
        "contrato_semantico_relevante.contrato_semantico.requisitos_mapeamento.campos_obrigatorios e a nova fonte o "
        "comprovar. Se a cobertura anterior for de campo estrutural ou fora dessa lista, "
        "remova-a; nao procure outra evidencia para ela. Preserve as partes validas da "
        "selecao, cubra todos os campos minimos exigidos e responda somente com este JSON "
        "completo, sem markdown ou explicacoes. O schema e estrito: em cada objeto "
        "de coberturas, use exclusivamente campo_saida e ancoras; campo nao e um "
        "atributo valido e ancoras deve conter textos literais do artefato. Formato: "
        "{\"tipo_artefato\":\"selecao_artefatos_layout\",\"artifact_paths\":[{"
        "\"path\":\"tables/table001.json\",\"motivo\":\"...\",\"coberturas\":[{"
        "\"campo_saida\":\"path.do.contrato\",\"ancoras\":[\"texto literal\"]}]}]}."
    )
