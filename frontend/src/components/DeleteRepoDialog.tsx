import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

interface DeleteRepoDialogProps {
  repoName: string;
  open: boolean;
  deleting: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
}

export default function DeleteRepoDialog({
  repoName, open, deleting, onOpenChange, onConfirm,
}: DeleteRepoDialogProps) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent className="border-[#c9c3b7] bg-[#fdfcf8] sm:max-w-md">
        <AlertDialogHeader>
          <AlertDialogTitle className="text-[#1a1d23]">
            Delete {repoName}?
          </AlertDialogTitle>
          <AlertDialogDescription className="text-[#5c6370]">
            This removes its graph and extracted claims. This action cannot be undone.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            disabled={deleting}
            onClick={onConfirm}
            className="bg-[#a45138] text-white hover:bg-[#8e432f]"
          >
            {deleting ? "Deleting…" : "Delete repository"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
