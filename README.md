# CineData Analyst — Agente Text-to-SQL

Agente que responde perguntas em linguagem natural sobre o catálogo de filmes da **CineData Analytics**,
gerando e executando consultas SQL **somente leitura** sobre a camada Gold (`cinerocket.db`, SQLite).

> "Top 10 filmes com maior receita em R$" → o agente escreve o SQL, executa no banco e responde em português.

## Stack

| Item | Escolha |
|---|---|
| Linguagem | Python 3.10+ |
| LLM | Modelos gratuitos do OpenRouter (`openrouter/free` + fallback para outros `:free`) |
| Framework de agente | Loop próprio de *tool calling* com o SDK `openai` (API compatível do OpenRouter) |
| Banco | SQLite (`cinerocket.db`, 10 tabelas do modelo dimensional) |
| Interface | Chat web com Streamlit (com gráficos) + CLI no terminal |

## Como funciona

```
pergunta ──► LLM (prompt com esquema + regras de negócio)
                │  chama a ferramenta run_sql(sql)
                ▼
         guardrails ──► SQLite (read-only) ──► linhas (máx. 50)
                │
                ▼
         LLM interpreta o resultado ──► resposta em português + tabela
```

- **`cinedata/prompts.py`**: esquema das tabelas e regras de negócio ("receita = faturamento = bilheteria",
  como tratar valores não informados, papel de ator/diretor em `dim_people.tipo_pessoa` etc.).
- **`cinedata/agent.py`**: loop do agente (até 5 chamadas ao LLM por pergunta), fallback entre modelos e memória.
- **`cinedata/db.py`**: execução segura das consultas.
- **`cinedata/cache.py`**: cache de respostas em disco.
- **`app.py`**: interface web de chat (Streamlit), com gráfico automático e SQL/dados em uma seção expansível.
- **`main.py`**: CLI.
- **`eval/`**: conjunto de avaliação com as perguntas do enunciado e o SQL esperado.

### Funcionalidades extras

- **Interface visual e gráficos**: chat no navegador (Streamlit) que mostra a resposta, um gráfico gerado
  automaticamente a partir do resultado (barras para rankings e linha para séries por ano), o SQL executado e a tabela de dados.
- **Guardrails em 3 camadas**: o banco é aberto em modo `ro`, a consulta precisa ser um único `SELECT`/`WITH`
  sem comandos de escrita, e um *authorizer* do SQLite nega qualquer operação que não seja leitura.
  Há ainda um timeout por consulta e um limite de linhas enviadas ao LLM. Perguntas fora do tema são recusadas.
- **Fallback entre modelos gratuitos**: se um modelo devolve 429 (pool lotado) ou outro erro, o agente passa
  para o próximo da lista. As re-tentativas automáticas do SDK ficam desligadas para não queimar a cota.
  Quando a cota diária acaba, o agente avisa e para.
- **Memória de conversa**: no modo interativo, perguntas de acompanhamento ("e só de 2020?") usam o contexto.
- **Cache de respostas** (`.cache/answers.json`): uma pergunta repetida não gasta requisição.
- **Avaliação**: `eval/questions.json` traz 14 perguntas do enunciado com o SQL de referência.

## Passo a passo para executar

### 1. Clonar e criar o ambiente

```bash
git clone https://github.com/juliamariateixeiraa/GenAI-Rocket.git
cd GenAI-Rocket
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Colocar o banco de dados

O `cinerocket.db` (~580 MB) **não está no repositório** porque passa do limite de 100 MB do GitHub.
Baixe-o da pasta do Drive da atividade e coloque-o na **raiz do projeto** com o nome `cinerocket.db`:

```
GenAI-Rocket/
├── cinerocket.db   ◄── aqui
├── main.py
└── ...
```

(Ou aponte para outro caminho com `CINEDATA_DB_PATH` no `.env`.)

### 3. Configurar a chave do OpenRouter

1. Crie uma conta em [openrouter.ai](https://openrouter.ai) e gere uma chave em [openrouter.ai/keys](https://openrouter.ai/keys).
2. Copie o arquivo de exemplo e cole sua chave:

```bash
cp .env.example .env
# edite .env -> OPENROUTER_API_KEY=sk-or-v1-...
```

### 4. Rodar

**Interface web (recomendado):**

```bash
streamlit run app.py
```

Abre em http://localhost:8501. Há perguntas de exemplo na barra lateral e o botão "Nova conversa" limpa a memória.

**Terminal**, com pergunta única:

```bash
python main.py "Top 10 filmes com maior receita em R$"
```

Ou no modo conversa do terminal (com memória; `/nova` limpa o contexto, `sair` encerra):

```bash
python main.py
```

Opções: `--no-sql` (esconde o SQL), `--no-cache` (ignora o cache), `-v` (mostra os logs de fallback).

### 5. Testes e avaliação

```bash
pytest                                   # guardrails + consultas de referência (sem usar o LLM)
python -m eval.run_eval --reference      # mostra as respostas esperadas (0 requisições)
python -m eval.run_eval --limit 3        # roda o agente em 3 perguntas e compara com o esperado
```

> ⚠️ A conta gratuita do OpenRouter permite **50 requisições/dia** (requisições com erro também contam),
> e cada pergunta usa de 2 a 3. A cota zera às 21h (horário de Brasília). Acompanhe em
> [openrouter.ai/activity](https://openrouter.ai/activity).

## Exemplos de perguntas

- **Bilheteria e finanças**: "Top 10 filmes com maior receita em R$", "Lucro médio por gênero considerando só filmes com receita informada", "Filmes com maior margem de lucro"
- **Popularidade**: "Os 5 filmes mais populares", "Filmes com maior divergência entre nota TMDB e IMDb", "Nota média IMDb por ano"
- **Elenco e equipe**: "Ator com mais filmes nos últimos 5 anos", "Diretores com maior nota média (mínimo 5 filmes)", "Dupla ator–diretor que mais trabalhou junta"
- **Gêneros e produtoras**: "Quantidade de filmes por gênero", "Produtora com maior lucro total", "Gênero com maior margem de lucro média"
- **Avaliações dos usuários**: "Filmes mais avaliados pelos usuários", "Filmes em que a nota dos usuários mais diverge da IMDb"

## Observações sobre os dados

- Receita/orçamento `NULL` ou `0` significam "não informado", e nesses casos `lucro_*` vem como `0`.
  Por isso as análises financeiras filtram `receita_usd > 0` (e `orcamento_usd > 0` para margem).
- `bridge_movie_person` não traz o papel da pessoa no filme. O papel (`Ator`, `Diretor`, `Roteirista`)
  está em `dim_people.tipo_pessoa`.
- Consultas que cruzam pessoas com pessoas (ex.: dupla ator–diretor) levam cerca de 30s no SQLite.
