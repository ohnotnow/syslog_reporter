from gepetto import anyscale, gpt, ollama, groq, claude

def get_bot(model="gpt-4o", vendor="unknown"):
    if model.startswith('gpt'):
        bot = gpt.GPTModelSync(model=model)
    elif model.startswith('claude'):
        bot = claude.ClaudeModelSync(model=model)
    elif vendor.startswith('ollama'):
        bot = ollama.OllamaModelSync(model=model)
    elif vendor.startswith('groq'):
        bot = groq.GroqModelSync(model=model)
    elif vendor.startswith('anyscale'):
        bot = anyscale.MistralModelSync(model=model)
    else:
        raise ValueError(f"Cannot find a bot for : {model} / {vendor}")
    return bot
