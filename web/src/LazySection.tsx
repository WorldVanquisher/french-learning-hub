import { Component, Suspense, type ReactNode } from "react";
import { useI18n } from "./i18n";

// LazySection shows a lazily loaded workbench section (React.lazy): a loading
// line while its file arrives, and, if the file cannot be loaded (most often
// because the server was upgraded and the old file is gone), a message with a
// reload button instead of a blank section. Vite's vite:preloadError also
// reaches freshness.tsx, which then checks for a newer version.
export function LazySection({ children }: { children: ReactNode }) {
  return (
    <LoadBoundary>
      <Suspense fallback={<SectionLoading />}>{children}</Suspense>
    </LoadBoundary>
  );
}

function SectionLoading() {
  const { t } = useI18n();
  return (
    <p className="hint" role="status">
      {t("app.lazy.loading")}
    </p>
  );
}

function SectionFailed() {
  const { t } = useI18n();
  return (
    <div className="banner error" role="alert">
      {t("app.lazy.failed")}{" "}
      <button type="button" onClick={() => window.location.reload()}>
        {t("app.newerVersion.reload")}
      </button>
    </div>
  );
}

class LoadBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? <SectionFailed /> : this.props.children;
  }
}
