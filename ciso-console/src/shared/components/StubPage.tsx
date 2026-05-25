// Placeholder for surfaces not yet wired in this session.
// CSM-2/3/4 will replace each stub with the real implementation.

interface StubPageProps {
  title: string;
  session: string;
}

export function StubPage({ title, session }: StubPageProps) {
  return (
    <div class="stub-page">
      <div class="stub-page-title">{title}</div>
      <div class="stub-page-subtitle">Coming in {session}</div>
    </div>
  );
}
