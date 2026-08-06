import { getAllStocks } from '@/lib/content';
import ReportTabs from '@/components/ReportTabs';

export default function DashboardPage() {
  return <ReportTabs stocks={getAllStocks()} />;
}
