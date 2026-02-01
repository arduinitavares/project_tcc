# CAPÍTULO 2 — Fundamentação teórica e trabalhos relacionados

Este capítulo apresenta os fundamentos teóricos que sustentam a pesquisa e sintetiza trabalhos relacionados relevantes. O foco recai sobre (i) o uso do Scrum e suas limitações práticas em equipes pequenas, (ii) o conceito de agentes autônomos e sistemas multiagentes baseados em Modelos de Linguagem de Grande Porte, (iii) a noção de governança por especificação, denominada no projeto de Spec-Driven Architecture e Specification Authority, e (iv) o posicionamento do trabalho frente ao estado da arte descrito nos documentos do projeto.

## 2.1 Scrum em equipes pequenas / limitações práticas

O Scrum é apresentado no Scrum Guide como um framework para desenvolvimento e manutenção de produtos complexos, apoiado no empirismo e estruturado para maximizar transparência, inspeção e adaptação. Sua aplicação prescreve papéis, eventos e artefatos, com ênfase na iteração e no incremento contínuo.

A adoção do Scrum na indústria é descrita, no material reunido neste trabalho, a partir de relatórios anuais setoriais e de documentação institucional. Especificamente, há menção ao “16th State of Agile Report” (Digital.ai, 2022) e a material institucional da Scrum.org (2023) como fontes que reportam essa predominância. Tais fontes, por sua natureza, descrevem tendências de adoção; elas não são, contudo, suficientes para garantir adequação metodológica em todos os contextos.

A limitação prática central em equipes de um a quatro desenvolvedores decorre da incompatibilidade entre a separação idealizada de papéis e a disponibilidade real de pessoas. O Scrum define três papéis distintos e interdependentes: Product Owner, Scrum Master e Developers. Em times muito pequenos, o acúmulo desses papéis por uma única pessoa tende a produzir tensão entre objetivos e responsabilidades que, em equipes maiores, tendem a ser distribuídos e equilibrados. Em particular, a mesma pessoa precisa alternar entre decisões estratégicas de produto, execução técnica e condução do processo, o que tende a aumentar carga operacional e carga cognitiva.

Em equipes pequenas, a separação deliberada de responsabilidades entre Product Owner, Scrum Master e Developers, descrita no Scrum Guide, pode se tornar difícil de sustentar na prática. Relatos e discussões de prática reunidos neste trabalho descrevem que, quando uma única pessoa acumula papéis, ocorre tensão entre objetivos e responsabilidades e tende a aumentar a carga operacional e cognitiva, especialmente em contextos de trabalho individual ou de times reduzidos.

Na literatura de prática e em discussões de comunidades técnicas, essa problemática é frequentemente discutida como um desafio de adequação do Scrum a contextos de escala reduzida.

Além do acúmulo de papéis, a própria prescrição de eventos formais e timeboxes pode impor custos proporcionais maiores quando o número de participantes é reduzido. Em termos operacionais, atividades como planejamento, sincronizações, revisões e retrospectivas demandam tempo e coordenação; em equipes pequenas, esse esforço tende a competir diretamente com o tempo de implementação de incrementos. Na literatura aplicada considerada neste trabalho, essa tensão é discutida em relatos de prática e em textos sobre “quando Scrum não se encaixa” em determinados contextos.

Do ponto de vista dos artefatos, o Scrum organiza o trabalho por meio de Product Backlog, Sprint Backlog e Incremento. Em equipes pequenas, a manutenção desses artefatos, associada às responsabilidades dos papéis, pode amplificar o custo administrativo. Esse cenário caracteriza um problema de adequação metodológica: não se trata apenas de automação de tarefas pontuais, mas de compatibilizar um conjunto de práticas concebidas para equipes com divisão de funções com um contexto em que essa divisão é limitada.

Os artefatos e suas responsabilidades associadas são descritos no Scrum Guide. Quanto ao argumento de que o custo administrativo associado à manutenção desses artefatos pode se tornar proporcionalmente mais oneroso em equipes pequenas, a literatura aplicada considerada neste trabalho aponta para discussões de prática em que se problematiza a adaptação do Scrum a contextos reduzidos.

Algumas afirmações de caráter prático, presentes na literatura aplicada e em discussões comunitárias, não puderam ser rastreadas de forma inequívoca a uma fonte acadêmica formal no material disponível; por transparência metodológica, registra-se:

[PLACEHOLDER: original source not identified]

## 2.2 Sistemas multiagentes e agentes com LLM

No escopo desta pesquisa, agentes autônomos baseados em Modelos de Linguagem de Grande Porte são tratados como entidades de software capazes de perceber informações do ambiente, deliberar sobre ações e executar tarefas para atingir objetivos definidos. Nos trabalhos analisados, esse funcionamento é descrito por meio de um ciclo de Percepção, Raciocínio e Ação, no qual o agente recebe entradas (por exemplo, requisitos e mensagens do usuário), processa essas informações e produz saídas, incluindo artefatos textuais e invocações de ferramentas.

A pesquisa também se baseia na noção de Sistema Multiagente, no qual múltiplos agentes especializados colaboram para alcançar um objetivo comum. A literatura de referência descreve três elementos recorrentes para essa colaboração: protocolos de comunicação, memória compartilhada e padrões de orquestração. Os protocolos de comunicação representam a forma pela qual agentes trocam informações de modo consistente. A memória compartilhada ou persistente permite que diferentes agentes operem sobre um estado comum do projeto, reduzindo perda de contexto entre etapas. Os padrões de orquestração, por sua vez, definem como a colaboração é coordenada, podendo assumir formas hierárquicas, sequenciais ou outras, conforme o desenho do sistema.

No material consultado, esses elementos aparecem associados a fontes como Lyu (2025), Deepchecks (2024), Microsoft (2025) e CrewAI (2025). Contudo, o material disponível não contém, de forma verificável, um mapeamento explícito que vincule cada componente a trechos específicos dessas fontes.

Na documentação técnica do projeto, descreve-se a adoção de um orquestrador que coordena agentes especializados ao longo de um fluxo conversacional e iterativo. O fluxo implementado no projeto é descrito como um pipeline de planejamento que progride por fases, incluindo visão de produto, compilação de especificação, construção de roadmap, geração de histórias de usuário, planejamento de sprint e execução. Também são descritos princípios operacionais associados a esse desenho, como agentes sem estado persistente próprio e a injeção de estado via estruturas JSON, além da persistência do estado conversacional em base SQLite.

Essa abordagem fundamenta-se em uma hipótese de engenharia: parte da carga de trabalho de coordenação e gestão de projeto pode ser deslocada para agentes especializados, reduzindo o esforço do usuário em conduzir atividades metodológicas e manter consistência entre artefatos.

## 2.3 Spec-Driven / governança por especificação

Além da simulação de papéis do Scrum, a documentação do projeto explicita uma camada adicional de governança por especificação, denominada Spec-Driven Architecture e Specification Authority. Nessa abordagem, a especificação técnica é tratada como fonte primária de verdade para escopo e restrições.

O plano de implementação da Spec-Driven Architecture descreve uma separação entre geração e aceitação de artefatos. A geração de artefatos permanece não determinística, pois é realizada por modelos de linguagem. Em contraste, a aceitação de artefatos é definida como determinística, baseada em validações do tipo passa ou falha. Essa distinção é apresentada como um mecanismo de controle para reduzir deriva de escopo e produzir decisões repetíveis de aceitação, mesmo quando a geração inicial é probabilística.

A documentação técnica descreve que a governança por especificação é operacionalizada por meio de um registro versionado de especificações e por artefatos compilados de autoridade. A compilação transforma a especificação em um conjunto de invariantes e gates de validação. O processo descrito inclui ingestão da especificação, compilação para um artefato de autoridade, aceitação dessa autoridade e, posteriormente, o uso do identificador de versão como âncora para etapas subsequentes.

O plano de Spec-Driven Architecture enfatiza um contrato de pinagem de autoridade como fronteira de validação. Nesse contrato, descreve-se que ferramentas públicas exigem explicitamente um identificador de versão da especificação, sem valores padrão. O carregamento da autoridade é descrito como centralizado em um único ponto lógico, e a aceitação da autoridade é tratada como condição para uso: um artefato compilado, por si só, não é considerado autoritativo sem um registro de aceitação. O mesmo documento também proíbe fontes implícitas de especificação, como leituras automáticas de campos de produto ou de versões mais recentes, como forma de reduzir ambiguidade e inconsistência.

No contexto do pipeline descrito, a geração de histórias de usuário é apresentada como dependente dessa autoridade compilada e aceita. A validação de histórias de usuário é descrita como pinada a uma versão específica da especificação, e o sistema é descrito como preservando essa pinagem para impedir que saídas geradas desviem do escopo estabelecido. A aceitação determinística, nesse desenho, atua como mecanismo de governança e auditabilidade, complementando a geração não determinística.

## 2.4 Trabalhos relacionados (tabela comparativa)

A literatura reunida para esta pesquisa inclui trabalhos correlatos que investigam sistemas multiagentes com modelos de linguagem aplicados à engenharia de software e a processos inspirados em práticas ágeis.

Um primeiro trabalho é a revisão de He e colaboradores (2024), que discute o uso de sistemas multiagentes baseados em modelos de linguagem na engenharia de software e descreve frameworks com agentes especializados para diferentes funções. No escopo sintetizado neste trabalho, esse tipo de revisão destaca desafios como fidelidade de papéis e necessidade de aprimoramento de protocolos de comunicação para aplicações mais complexas.

Um segundo trabalho é o framework CogniSim, atribuído a Cinkusz e Chudziak (2025), descrito na literatura considerada como voltado à simulação de uma equipe Scrum completa em ambientes de larga escala, com menção a contextos como SAFe e a protocolos formais de comunicação. No escopo sintetizado neste trabalho, a avaliação desse tipo de abordagem foi associada a simulações de cerimônias ágeis e a métricas de qualidade de artefatos e de alinhamento de objetivos.

Um terceiro trabalho é o sistema AgileCoder, de Nguyen e colaboradores (2024), caracterizado como uma tentativa de emular ciclos de Sprint do Scrum por meio de múltiplos agentes e mecanismos de manutenção de contexto. No material reunido, a avaliação é descrita com uso de benchmarks de programação e estudos de ablação para medir o impacto de componentes do sistema.

Este capítulo apresenta a comparação de forma textual, destacando os pontos de convergência e divergência que são relevantes para o escopo desta pesquisa.

## 2.5 Lacunas e posicionamento do seu trabalho

No material revisado e sintetizado neste trabalho, o estado da arte descrito aparece concentrado em dois eixos principais. No primeiro eixo, sistemas multiagentes são empregados para automatizar o ciclo de desenvolvimento de software, com foco em gerar código, revisar e testar, aproximando-se de uma substituição ou aumento de equipes convencionais. No segundo eixo, sistemas são orientados a contextos organizacionais de grande escala, com simulação de papéis e cerimônias em ambientes complexos.

A lacuna identificada no escopo desta pesquisa é a ausência de uma solução voltada diretamente para a incompatibilidade metodológica enfrentada por equipes muito pequenas ao tentar aplicar Scrum. Em particular, os trabalhos correlatos descritos enfatizam automação do desenvolvimento ou simulação em escala, sem focar, de forma explícita, em apoiar um desenvolvedor humano que precisa acumular papéis e manter artefatos de planejamento e execução em um fluxo inspirado no Scrum.

O artefato desenvolvido neste trabalho é uma plataforma de gestão ágil autônoma que atua como uma equipe de suporte virtual para equipes de um a quatro desenvolvedores, com ênfase em orquestrar um fluxo de trabalho inspirado no Scrum do ponto de vista de gestão e planejamento. Um diferencial descrito na documentação do projeto é a camada de governança por especificação, na qual a especificação versionada e a autoridade compilada condicionam a aceitação de artefatos por validações determinísticas e por pinagem de versão. Nesse enquadramento, a contribuição não é apenas automatizar tarefas isoladas, mas estruturar um fluxo de trabalho conversacional com persistência de estado e mecanismos explícitos de controle de escopo e rastreabilidade.
