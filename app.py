"""Interface web (chat) do CineData Analyst.

    streamlit run app.py
"""

import pandas as pd
import streamlit as st

from cinedata.agent import AllModelsFailedError, CineDataAgent, QuotaExceededError
from cinedata.db import CineDB

st.set_page_config(page_title="CineData Analyst", page_icon="🎬", layout="wide")

EXAMPLES = [
    "Top 10 filmes com maior receita em R$",
    "Quantidade de filmes por gênero",
    "Nota média IMDb por ano de lançamento",
    "Produtora com maior lucro total",
    "Diretores com maior nota média (mínimo de 5 filmes)",
    "Filmes mais avaliados pelos usuários",
]

AVATARS = {"user": "🍿", "assistant": "🎬"}


@st.cache_resource
def get_db() -> CineDB:
    return CineDB()


@st.cache_data(show_spinner=False)
def catalog_stats() -> dict:
    """Números do catálogo para os cartões do topo (direto do banco, sem usar o LLM)."""
    db = get_db()
    one = lambda sql: db.run(sql).rows[0][0]
    return {
        "Filmes": f"{one('SELECT COUNT(*) FROM dim_movies'):,}".replace(",", "."),
        "Gêneros": one("SELECT COUNT(*) FROM dim_genres"),
        "Produtoras": f"{one('SELECT COUNT(*) FROM dim_companies'):,}".replace(",", "."),
        "Período": one("SELECT MIN(ano_lancamento) || '–' || MAX(ano_lancamento) FROM dim_movies"),
    }


def get_agent() -> CineDataAgent:
    # Um agente por sessão do navegador, para a memória de conversa não se misturar.
    if "agent" not in st.session_state:
        st.session_state.agent = CineDataAgent(db=get_db())
    return st.session_state.agent


def to_dataframe(ans) -> pd.DataFrame | None:
    result = ans.result
    if result is None and ans.queries:  # resposta vinda do cache: reexecuta a consulta (só leitura)
        try:
            result = get_db().run(ans.queries[-1])
        except Exception:
            return None
    if result is None or not result.rows:
        return None
    return pd.DataFrame(result.rows, columns=result.columns)


def render_chart(df: pd.DataFrame):
    """Gráfico automático: 1ª coluna como eixo/categoria e a 1ª coluna numérica como valor."""
    if df is None or len(df) < 2 or len(df.columns) < 2:
        return
    numeric = [c for c in df.columns[1:] if pd.api.types.is_numeric_dtype(df[c])]
    if not numeric:
        return
    x, y = df.columns[0], numeric[0]
    data = df[[x, y]].dropna()
    if pd.api.types.is_integer_dtype(data[x]) and data[x].between(1900, 2100).all():
        st.line_chart(data, x=x, y=y, color="#E50914")  # série temporal (ex.: ano)
    elif not pd.api.types.is_numeric_dtype(data[x]):
        data = data.drop_duplicates(subset=x)
        st.bar_chart(data, x=x, y=y, horizontal=True, sort=f"-{y}", color="#E50914")


def render_answer(ans):
    st.markdown(ans.answer)
    df = to_dataframe(ans)
    render_chart(df)
    if ans.queries:
        with st.expander("Ver SQL e dados"):
            st.code(ans.queries[-1], language="sql")
            if df is not None:
                st.dataframe(df, width="stretch", hide_index=True)
    origem = "⚡ cache" if ans.cached else f"🤖 {ans.model} · {ans.llm_calls} chamada(s) ao LLM"
    st.caption(origem)


# ---------- Layout ----------
with st.sidebar:
    st.title("🎬 CineData Analyst")
    st.write("Pergunte em português sobre o catálogo de filmes. O agente gera o SQL, consulta a "
             "camada Gold (somente leitura) e explica o resultado.")
    usage_slot = st.empty()  # preenchido no fim do script, depois de a pergunta ser respondida
    st.subheader("Exemplos")
    for ex in EXAMPLES:
        if st.button(ex, width="stretch"):
            st.session_state.pending = ex
            st.rerun()
    st.divider()
    if st.button("🧹 Nova conversa", width="stretch"):
        st.session_state.messages = []
        if "agent" in st.session_state:
            st.session_state.agent.reset()
        st.rerun()
    st.caption("Plano gratuito do OpenRouter: 50 requisições/dia (~2–3 por pergunta), "
               "zera às 21h (Brasília). Perguntas repetidas vêm do cache.")

try:
    agent = get_agent()
except (RuntimeError, FileNotFoundError) as exc:
    st.error(str(exc))
    st.stop()

st.session_state.setdefault("messages", [])
question = st.chat_input("Ex.: Qual gênero tem a maior margem de lucro média?")
question = question or st.session_state.pop("pending", None)

st.markdown("## 🎬 Converse com os dados do :red[CineData]")
for col, (label, value) in zip(st.columns(4), catalog_stats().items()):
    col.metric(label, value, border=True)

if not st.session_state.messages and not question:
    # Tela de boas-vindas: perguntas de exemplo no centro da página.
    st.markdown("#### O que você quer descobrir sobre o catálogo?")
    st.caption("Escolha um exemplo ou digite sua pergunta no campo abaixo.")
    cols = st.columns(3)
    for i, ex in enumerate(EXAMPLES):
        if cols[i % 3].button(ex, key=f"welcome_{i}", width="stretch"):
            st.session_state.pending = ex
            st.rerun()

for msg in st.session_state.messages:
    with st.chat_message(msg["role"], avatar=AVATARS[msg["role"]]):
        if msg["role"] == "user":
            st.markdown(msg["content"])
        else:
            render_answer(msg["content"])

if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user", avatar=AVATARS["user"]):
        st.markdown(question)
    with st.chat_message("assistant", avatar=AVATARS["assistant"]):
        try:
            with st.spinner("Consultando o catálogo... (modelos gratuitos podem levar até 1 min)"):
                ans = agent.ask(question)
        except QuotaExceededError as exc:
            st.warning(str(exc))
            st.stop()
        except AllModelsFailedError as exc:
            st.error(f"Os modelos gratuitos não responderam agora. Tente de novo em instantes.\n\n{exc}")
            st.stop()
        render_answer(ans)
    st.session_state.messages.append({"role": "assistant", "content": ans})


def render_usage(slot, usage: dict | None):
    if not usage:
        return
    used, limit = usage.get("used", 0), usage.get("limit") or 50
    with slot.container():
        left, right = st.columns([3, 1])
        left.caption("Requisições hoje")
        right.caption(f"**{used}/{limit}**")
        st.progress(min(used / limit, 1.0))


render_usage(usage_slot, agent.daily_usage())
