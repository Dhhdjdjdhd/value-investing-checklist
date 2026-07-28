import { getAllStocks } from '@/lib/content';
import ReportTabs from '@/components/ReportTabs';

export default function HomePage() {
  return <ReportTabs stocks={getAllStocks()} />;
}
