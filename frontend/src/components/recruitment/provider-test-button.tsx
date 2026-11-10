"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Loader2, PlugZap } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";

/** HRP-986: "Test connection" on a provider row of the LLM and the
 *  transcription settings pages - one POST to the row's `/test` endpoint,
 *  which answers ok or a localized reason; both land in a toast. */
export function ProviderTestButton({
  url,
  okMessage,
  testId,
}: {
  url: string;
  okMessage: string;
  testId: string;
}) {
  const t = useTranslations("recruitment");
  const [testing, setTesting] = useState(false);

  async function handleTest() {
    setTesting(true);
    try {
      await api.post(url);
      toast.success(okMessage);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toastGenericError"));
    } finally {
      setTesting(false);
    }
  }

  return (
    <Button
      size="sm"
      variant="ghost"
      onClick={handleTest}
      disabled={testing}
      data-testid={testId}
    >
      {testing ? (
        <Loader2 className="size-3.5 animate-spin" />
      ) : (
        <PlugZap className="size-3.5" />
      )}
      {t("llmTestButton")}
    </Button>
  );
}
