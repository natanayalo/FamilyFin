"use client";

import { useParams } from "next/navigation";
import { SignIn } from "@/components/sign-in";
import { useAppAuth } from "@/components/app-provider";
import { sections, Workspace } from "@/components/workspace";
import { LoadingState, ReconnectState } from "@/components/ui/async-state";

export default function SectionPage() {
  const params = useParams<{ section: string }>();
  const { auth, online } = useAppAuth();
  if (!sections.some((item) => item.id === params.section)) return <main className="loading-screen">העמוד לא נמצא.</main>;
  if (auth.status === "loading") return <main className="loading-screen"><LoadingState label="בודקים את החיבור המאובטח…" /></main>;
  if ((auth.status === "signed-in" && online) || (auth.status === "offline" && auth.session)) return <Workspace sectionId={params.section} />;
  if (auth.status === "offline") return <main className="reconnect-screen"><ReconnectState /></main>;
  return <SignIn />;
}
