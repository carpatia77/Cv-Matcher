import asyncio

from openai import AsyncOpenAI

from app.config import settings


async def check_models():
    print(f"Verificando NVIDIA_API_KEY: {'[CONFIGURADA]' if settings.NVIDIA_API_KEY else '[NÃO ENCONTRADA]'}")
    if not settings.NVIDIA_API_KEY:
        print("Erro: NVIDIA_API_KEY está vazia no .env!")
        return

    client = AsyncOpenAI(
        api_key=settings.NVIDIA_API_KEY,
        base_url=settings.NVIDIA_BASE_URL,
    )

    try:
        print("Consultando endpoints/modelos disponíveis na NVIDIA NIM...")
        response = await client.models.list()
        model_ids = [m.id for m in response.data]
        print(f"\nTotal de modelos encontrados: {len(model_ids)}")
        print("\n--- MODELOS DEEPSEEK DISPONÍVEIS ---")
        deepseek_models = [m for m in model_ids if 'deepseek' in m.lower()]
        for dm in deepseek_models:
            print(f" - {dm}")

        print("\n--- OUTROS MODELOS EM DESTAQUE (LLAMA / MISTRAL / NV-EMBED) ---")
        for m in sorted(model_ids):
            if any(x in m.lower() for x in ('llama', 'mistral', 'embed', 'nemotron')):
                print(f" - {m}")

    except Exception as e:
        print(f"Erro ao comunicar com a API NVIDIA: {e}")
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(check_models())
