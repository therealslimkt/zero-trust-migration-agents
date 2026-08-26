import asyncio
from google.antigravity import Agent, LocalAgentConfig
import os

async def main():
    os.environ['GOOGLE_CLOUD_PROJECT'] = 'ztm-agent-9049c3'
    c = LocalAgentConfig(model='gemini-3.5-flash', vertex=True, location='asia-northeast1', project='ztm-agent-9049c3', system_instructions="You are a helpful researcher.")
    a = Agent(config=c)
    async with a:
        res = await a.chat('say hi')
        print(await res.text())

asyncio.run(main())
