import { MongoClient, Db } from 'mongodb';

// MongoDB Atlas 연결 — momcare와 같은 방식(MONGODB_URI 환경변수).
// Next.js는 개발 중 모듈을 자주 다시 로드하므로 연결 프로미스를 global에 캐시한다.
const g = globalThis as unknown as { _mongoClient?: Promise<MongoClient> };

export async function getDb(): Promise<Db> {
  const uri = process.env.MONGODB_URI;
  if (!uri) throw new Error('MONGODB_URI 환경변수가 설정되지 않았습니다.');
  if (!g._mongoClient) {
    // 실패한 연결을 캐시하면 서버가 재시작될 때까지 /api/hold가 계속 503 — 실패하면 비워서 다음 요청이 다시 붙게 한다
    g._mongoClient = new MongoClient(uri).connect().catch((e) => {
      g._mongoClient = undefined;
      throw e;
    });
  }
  return (await g._mongoClient).db(process.env.MONGODB_DB || 'vic');
}
