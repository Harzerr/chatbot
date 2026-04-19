import asyncio
from app.services.resume_parser import ResumeParserService

async def main():
    s = ResumeParserService()
    print('pdftotext_cmd=', s._pdftotext_cmd)
    t = await s.extract_text('uploads/resumes/user_6_b1261b08ff664c86910c67311018cd2a.pdf', 'application/pdf')
    print('len=', len(t))
    print(t[:400])

asyncio.run(main())
