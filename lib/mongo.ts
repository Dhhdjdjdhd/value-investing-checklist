import { MongoClient, Db } from 'mongodb';

// MongoDB Atlas 연결 — momcare와 같은 방식(MONGODB_URI 환경변수).
// Next.js는 개발 중 모듈을 자주 다시 로드하므로 연결 프로미스를 global에 캐시한다.
const g = globalThis as unknown as { _mongoClient?: Promise<MongoClient> };

export async function getDb(): Promise<Db> {
  const uri = process.env.MONGODB_URI;
  if (!uri) throw new Error('MONGODB_URI 환경변수가 설정되지 않았습니다.');
  if (!g._mongoClient) g._mongoClient = new MongoClient(uri).connect();
  return (await g._mongoClient).db(process.env.MONGODB_DB || 'vic');
}
