"use client";

import { SignIn } from "@/components/sign-in";
import { useAppAuth } from "@/components/app-provider";
import { Workspace } from "@/components/workspace";
import { LoadingState, ReconnectState } from "@/components/ui/async-state";

export default function HomePage() {
  const { auth, online } = useAppAuth();
  if (auth.status === "loading") return <main className="loading-screen"><LoadingState label="בודקים את החיבור המאובטח…" /></main>;
  if ((auth.status === "signed-in" && online) || (auth.status === "offline" && auth.session)) return <Workspace />;
  if (auth.status === "offline") return <main className="reconnect-screen"><ReconnectState /></main>;
  return <SignIn />;
}
