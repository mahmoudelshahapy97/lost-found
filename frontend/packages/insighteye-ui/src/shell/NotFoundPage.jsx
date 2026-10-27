import { Link as RouterLink } from "react-router-dom";
import Button from "@mui/material/Button";
import SearchOffIcon from "@mui/icons-material/SearchOff";
import { useTranslation } from "react-i18next";
import { EmptyState } from "../components/DataStates";

export function NotFoundPage() {
  const { t } = useTranslation("common");
  return (
    <EmptyState
      icon={<SearchOffIcon fontSize="inherit" />}
      title={t("notFound.title")}
      description={t("notFound.body")}
      action={
        <Button component={RouterLink} to="/" variant="contained">
          {t("notFound.home")}
        </Button>
      }
    />
  );
}

export default NotFoundPage;
