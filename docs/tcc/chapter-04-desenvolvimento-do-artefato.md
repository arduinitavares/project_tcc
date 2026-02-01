# CAPÍTULO 4 — Desenvolvimento do artefato

Este capítulo descreve o processo de engenharia e a implementação técnica da Plataforma de Gestão Ágil Autônoma. São detalhados os requisitos funcionais e não funcionais que nortearam o desenvolvimento, a arquitetura de software adotada, os componentes principais do sistema multiagente, o esquema de persistência e as decisões de implementação que viabilizaram a governança por especificação.

## 4.1 Visão geral e requisitos

O artefato desenvolvido é uma plataforma de software que orquestra agentes autônomos para executar um fluxo de trabalho de gestão ágil inspirado no Scrum. O objetivo técnico central foi criar um sistema capaz de interpretar intenções humanas vagas e convertê-las em artefatos de engenharia estruturados (histórias de usuário, planos de sprint), mantendo a rastreabilidade e a consistência lógica.

### 4.1.1 Requisitos funcionais

Os requisitos funcionais foram derivados da necessidade de simular os papéis do Scrum descritos na fundamentação teórica:

-   **RF01 — Definição de Visão:** O sistema foi projetado para permitir que o usuário defina a visão do produto por meio de diálogo em linguagem natural, estruturando as informações em componentes canônicos (público-alvo, problema, solução).
-   **RF02 — Governança por Especificação:** O sistema implementa um registro versionado de especificações técnicas visando impedir a criação de artefatos derivados (como histórias de usuário) que contradigam a versão vigente (*Authority Pinning*).
-   **RF03 — Geração de Backlog:** O sistema foi projetado para gerar histórias de usuário compatíveis com estruturas do critério INVEST, extraídas automaticamente da visão e da especificação técnica.
-   **RF04 — Planejamento de Sprints:** O sistema implementa mecanismos para sugerir o planejamento de ciclos de trabalho (*Sprints*) com base na capacidade da equipe e na prioridade dos itens, respeitando *timeboxes* definidos.
-   **RF05 — Execução e Monitoramento:** O sistema implementa o registro de progresso e o cálculo de métricas de fluxo (*Cycle Time*) e esforço.

### 4.1.2 Requisitos não funcionais e restrições

As restrições técnicas visaram garantir a reprodutibilidade e a auditabilidade do sistema:

-   **RNF01 — Determinismo na Aceitação:** Embora a geração de conteúdo utilize modelos probabilísticos (LLMs), a validação e aceitação de artefatos foram implementadas seguindo regras determinísticas baseadas em esquemas de dados estritos.
-   **RNF02 — Agentes sem Estado Persistente Próprio:** Para evitar divergência de comportamento, os agentes não mantêm memória interna oculta. Todo o estado é persistido em banco de dados e reinjetado no contexto a cada interação (*Stateless Design*).
-   **RNF03 — Rastreabilidade de Métricas:** O sistema registra eventos de fluxo (*WorkflowEvents*) de forma nativa para fornecer dados de tempos de execução e suportar a coleta de instrumentos externos de avaliação (como *inputs* para NASA-TLX).

## 4.2 Arquitetura do sistema

A arquitetura descrita a seguir corresponde à implementação efetiva do artefato analisado neste estudo. A arquitetura adotada segue o padrão de **Orquestração Centralizada** (*Hub-and-Spoke*), onde um Agente Orquestrador atua como controlador de fluxo e roteador, acionando tarefas complexas para Agentes Especializados.

### 4.2.1 Visão lógica

O sistema é composto por três camadas principais:

1.  **Camada de Orquestração:** Responsável pela interação com o usuário, interpretação de intenções e gerenciamento da máquina de estados do fluxo de trabalho.
2.  **Camada de Especialistas (Agents & Tools):** Conjunto de módulos encapsulados que executam tarefas específicas (ex: compilador de autoridade, gerador de histórias). Cada especialista possui seu próprio conjunto de instruções e ferramentas.
3.  **Camada de Persistência e Memória:** Infraestrutura de dados que armazena o estado do projeto, as especificações e os registros de eventos.

### 4.2.2 Pilha tecnológica

A implementação utilizou as seguintes tecnologias, selecionadas conforme a matriz de decisão da metodologia:

-   **Linguagem:** Python 3.12+, escolhido pela robustez do ecossistema de IA e tipe de dados.
-   **Framework de Agentes:** Google ADK (*Agent Development Kit*), utilizado para estruturar os agentes e ferramentas. A escolha deve-se à sua capacidade de integrar chamadas de funções (*Function Calling*) com controle de fluxo tipado.
-   **Integração LLM:** LiteLLM v1.78+, atuando como camada de abstração para conexão com provedores de inferência compatíveis com a API OpenAI (via OpenRouter).
-   **Persistência:** SQLModel (sobre SQLAlchemy) e banco de dados SQLite, oferecendo validação de esquema em tempo de execução e integridade referencial.

## 4.3 Componentes principais

A seguir, detalham-se os componentes de software que materializam a arquitetura proposta.

### 4.3.1 O Orquestrador (Orchestrator Agent)

O `orchestrator_agent` é o ponto de entrada do sistema. Ele opera como uma máquina de estados implícita, guiada por um arquivo de instruções mestre (`instructions.txt`). Sua responsabilidade primária é manter o contexto da conversa e decidir qual ferramenta ou subagente acionar.

Diferente de abordagens puramente reativas, o orquestrador possui acesso a ferramentas de leitura de estado (`get_project_details`, `list_sprints`), permitindo que ele tome decisões informadas sobre o progresso do projeto antes de responder ao usuário.

### 4.3.2 Registro de Especificações e Authority Pinning

Um dos diferenciais técnicos do artefato é o módulo `SpecRegistry`. Implementado em `tools/spec_tools.py`, este componente resolve o problema da alucinação e deriva de escopo em sistemas generativos.

O mecanismo de **Authority Pinning** funciona da seguinte forma:
1.  O usuário fornece uma especificação técnica (texto ou arquivo).
2.  O sistema gera um *hash* único do conteúdo e cria uma versão imutável no banco de dados.
3.  Um agente compilador (`Spec Authority Compiler`) processa o texto e extrai invariantes lógicas (regras de negócio, restrições técnicas).
4.  Este artefato compilado (`CompiledSpecAuthority`) recebe um identificador de versão.
5.  Qualquer operação subsequente de geração de histórias (`UserStory`) exige a vinculação explícita a esse ID de versão. Se a especificação mudar, o ID muda, invalidando artefatos obsoletos até que sejam reconciliados.

Essa implementação garante que a "verdade" do projeto seja um artefato versionado e auditável, e não a memória efêmera do modelo de linguagem.

### 4.3.3 Pipeline de Histórias (INVEST Validation Loop)

O componente `Story Pipeline` implementa a geração de backlogs com garantia de qualidade estrutural. Em vez de uma única chamada ao LLM ("gere histórias"), o sistema executa um laço de retroalimentação:

1.  **Geração:** O modelo propõe um conjunto de histórias baseadas na *Spec Authority*.
2.  **Validação:** Um validador lógico verifica se cada história atende a requisitos estruturais e sintáticos derivados do critério INVEST (ex: presença de critérios de aceitação, campos de estimativa), atuando como um *proxy* automatizável para a qualidade do artefato, sem substituir a avaliação semântica humana completa.
3.  **Refinamento:** Se a validação falha, o erro é reinjetado no contexto do agente, que é instruído a reprocessar a saída.
4.  **Persistência:** Apenas histórias validadas são persistidas no banco de dados.

### 4.3.4 Agente de Planejamento de Sprints

O planejador (`Sprint Planning`) atua como um assistente para alocação de trabalho. Ele utiliza ferramentas como `get_backlog_for_planning` para visualizar itens pendentes e `plan_sprint_tool` para sugerir uma distribuição de tarefas que caiba na capacidade do time (simulada ou informada), respeitando a precedência e a prioridade dos itens.

## 4.4 Modelo de dados e persistência

A robustez do sistema é garantida por um esquema relacional estrito, definido via SQLModel. As principais entidades do modelo (`agile_sqlmodel.py`) incluem:

-   **Project:** A raiz de agregação.
-   **SpecRegistry:** Armazena versões de especificações e seus *hashes*.
-   **UserStory:** Representa itens de trabalho, com campos para critérios de aceitação, estimativa e *links* para a autoridade de especificação.
-   **Sprint:** Representa os ciclos de tempo, contendo datas de início/fim e status.
-   **WorkflowEvent:** Tabela de *log* estruturado utilizada para armazenar métricas para a avaliação (tipo de evento, *timestamp*, duração, carga cognitiva reportada).

O uso de SQLite como motor de banco de dados simplifica a implantação local do artefato, mantendo a capacidade de consultas relacionais complexas necessárias para os relatórios de validação.

## 4.5 Considerações de implementação

Durante o desenvolvimento, algumas decisões técnicas foram críticas para atender aos objetivos da pesquisa:

-   **Abstração de Modelo (LiteLLM):** A decisão de usar `LiteLLM` permitiu desacoplar a lógica do sistema do provedor de IA específico. Isso facilita a troca de modelos (ex: de GPT-4 para Claude 3 ou modelos locais) sem refatoração de código, aumentando a longevidade do artefato.
-   **Validação de Esquema (Pydantic):** Todas as entradas e saídas de ferramentas são tipadas com Pydantic. Isso impede que "alucinações" de formato (ex: JSON malformado) propaguem erros para o banco de dados, atuando como um *firewall* de integridade de dados.
-   **Cache de Ferramentas:** Para otimizar a latência e o custo, implementou-se um mecanismo de cache para ferramentas de leitura pesada (como a leitura da especificação completa), reduzindo o tempo de resposta do orquestrador em interações sequenciais.

Este capítulo apresentou a materialização técnica da proposta. A arquitetura modular e o foco em governança por especificação formam a base sobre a qual os experimentos de validação e avaliação, descritos nos capítulos subsequentes, foram realizados.
