import { notFound } from "next/navigation";

/** Unknown paths render the report group's not-found page, inside the running head. */
export default function Missing() {
  notFound();
}
