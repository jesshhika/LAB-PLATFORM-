import LabWorkspace from "@/components/lab-workspace";

type PageProps = {
  params: Promise<{ sessionId: string }>;
};

export default async function LabPage({ params }: PageProps) {
  const { sessionId } = await params;
  return <LabWorkspace sessionId={sessionId} />;
}
